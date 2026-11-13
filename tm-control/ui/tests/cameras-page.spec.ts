// The Cameras page: one panel per camera, the intro, Frigate's state, and the save of the settings a panel opens to.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { ADMIN, apiError, camerasState, cameraRow, json, newRow, signedIn } from './fake-api'
import { buttonsIn, click, clickIn, clickInDialog, dialogButtons, dialogText, fieldIn, mountApp } from './mount'

const CAMERAS = 'GET /api/v1/cameras'

const WIDE = cameraRow()
const TELE = cameraRow({
  name: 'camera_2_9d41e0',
  frigate_camera: 'oak_ave_tele',
  camera_radar: 'TM_RADAR_SERIAL_PORT_00',
  zones_missing: ['zone_near', 'zone_far'],
})

async function openPage(state = camerasState({ rows: [WIDE, TELE] }), extra: Record<string, unknown> = {}) {
  const api = signedIn(ADMIN, { [CAMERAS]: state, ...extra })
  const { wrapper } = await mountApp('/cameras')
  return { api, wrapper }
}

// The page's camera rows, each an expansion panel
function rowItems(wrapper: VueWrapper) {
  return wrapper.findAll('.v-expansion-panel')
}

function names(wrapper: VueWrapper) {
  return wrapper.findAll('.v-expansion-panel .font-weight-bold').map((node) => node.text())
}

// Open a row's panel by its header, as a person would, and return its settings form
async function openRow(wrapper: VueWrapper, index = 0) {
  await rowItems(wrapper)[index].find('.v-expansion-panel-title').trigger('click')
  await flushPromises()
  return rowItems(wrapper)[index].find('form').element
}

function openRows(wrapper: VueWrapper) {
  return wrapper.findAll('.v-expansion-panel--active')
}

// The buttons on the rows for what to do with a camera, not the panels' headers or an open form's
function actionTexts(wrapper: VueWrapper) {
  return wrapper.findAll('[data-actions] button').map((b) => b.text())
}

describe('Cameras page', () => {
  it('lists each camera: its key in bold with its Frigate name beside it', async () => {
    const { wrapper } = await openPage()
    expect(wrapper.find('h1').text()).toBe('Cameras')
    expect(names(wrapper)).toEqual(['camera_1_3fa9c2', 'camera_2_9d41e0'])
    expect(wrapper.text()).toContain('oak_ave_wide')
    expect(wrapper.text()).toContain('oak_ave_tele')
  })

  it("says what the page is for, and links to Frigate's own page", async () => {
    const { wrapper } = await openPage()
    expect(wrapper.text()).toContain(
      'Frigate owns each camera: its name, streams, and zones. This page sets what the Traffic Monitor does with it. ' +
        "The name in bold is the one saved with the data. Frigate's name stays on this device.",
    )
    expect(wrapper.find('a[href="/frigate/"]').text()).toBe('Open Frigate')
    expect(wrapper.text()).toContain("Open Frigate to add a camera or change a camera's name, streams, or zones.")
  })

  it("shows each camera's settings and zones", async () => {
    const { wrapper } = await openPage()
    const text = wrapper.text()
    expect(text).toContain('Zones: all four')
    expect(text).toContain('Missing in Frigate: zone_near, zone_far')
    expect(text).toContain('Radar: TM_RADAR_SERIAL_PORT_00')
    expect(text).toContain('Radar: none')
    expect(text).toContain('Frigate detection: on')
    expect(text).toContain('Database capture: on')
  })

  it("says when Frigate's detection or the database capture is off", async () => {
    const rows = [cameraRow({ detect: false }), cameraRow({ name: 'camera_2_9d41e0', enabled: false })]
    const { wrapper } = await openPage(camerasState({ rows }))
    const lines = rowItems(wrapper).map((item) => item.text())
    expect(lines[0]).toContain('Frigate detection: off')
    expect(lines[0]).toContain('Database capture: on')
    expect(lines[1]).toContain('Frigate detection: on')
    expect(lines[1]).toContain('Database capture: off')
  })

  it('marks each row the Status page reports in its color, and says how many above the list', async () => {
    const detectOff = cameraRow({ detect: false, issues: [{ level: 'warn', code: 'detect_off' }] })
    const { wrapper } = await openPage(camerasState({ rows: [detectOff, TELE, newRow('main_st')] }))
    const summary = wrapper.find('[data-summary]')
    expect(summary.text()).toBe('2 cameras need attention. Each marked row says why.')
    expect(summary.classes()).toContain('text-error')
    const rows = rowItems(wrapper)
    expect(rows[0].find('[data-issue]').classes()).toContain('text-warning')
    expect(rows[0].find('[data-issue]').text()).toBe("Not recorded: Frigate's detection is off. Turn it on in Settings.")
    expect(rows[1].find('[data-issue]').exists()).toBe(false)
    expect(rows[2].find('[data-issue]').classes()).toContain('text-error')
  })

  it("says one camera in the summary, in the warning color, and links a zones box to Frigate's zones", async () => {
    const zones = cameraRow({ zones_missing: ['zone_far'], issues: [{ level: 'warn', code: 'zones' }] })
    const { wrapper } = await openPage(camerasState({ rows: [zones] }))
    const summary = wrapper.find('[data-summary]')
    expect(summary.text()).toBe('1 camera needs attention. Each marked row says why.')
    expect(summary.classes()).toContain('text-warning')
    const link = wrapper.find('[data-issue] a')
    expect(link.text()).toBe('Edit its zones in Frigate')
    expect(link.attributes('href')).toBe('/frigate/settings?page=masksAndZones&camera=oak_ave_wide')
    expect(wrapper.text().split('Missing in Frigate: zone_far').length - 1).toBe(1) // said once, in the box
  })

  it('has no summary when nothing needs attention', async () => {
    const { wrapper } = await openPage()
    expect(wrapper.find('[data-summary]').exists()).toBe(false)
    expect(wrapper.find('[data-issue]').exists()).toBe(false)
  })

  it('shows the plates setting only when the add-on is installed', async () => {
    const without = await openPage()
    expect(without.wrapper.text()).not.toContain('Plates')
    const withPlates = await openPage(camerasState({ plates: true, rows: [cameraRow({ plate_recognizer: true })] }))
    expect(withPlates.wrapper.text()).toContain('Plates: on')
  })

  it('marks a camera that is off in Frigate', async () => {
    const { wrapper } = await openPage(camerasState({ rows: [cameraRow({ in_frigate: 'off' })] }))
    expect(wrapper.text()).toContain('Off in Frigate')
  })

  it('marks an entry whose Frigate camera is gone and one that repeats another', async () => {
    const { wrapper } = await openPage(
      camerasState({
        rows: [
          cameraRow({ in_frigate: 'absent', zones_missing: null, issues: [{ level: 'warn', code: 'gone' }] }),
          cameraRow({
            name: 'camera_2_9d41e0',
            duplicate_of: 'camera_1_3fa9c2',
            issues: [{ level: 'error', code: 'duplicate' }],
          }),
        ],
      }),
    )
    expect(wrapper.text()).toContain('Frigate no longer has oak_ave_wide.')
    expect(wrapper.text()).toContain('camera_1_3fa9c2 already records this Frigate camera.')
  })

  it('lists a Frigate camera that no entry points at as not recorded, without a radar', async () => {
    const { wrapper } = await openPage(camerasState({ rows: [WIDE, newRow()] }))
    expect(wrapper.text()).toContain("oak_ave_tele is new in Frigate and isn't recorded.")
    const fresh = rowItems(wrapper)[1].text()
    expect(fresh).toContain('Frigate detection: on')
    expect(fresh).toContain('Database capture: off')
    expect(fresh).not.toContain('Radar')
  })

  it.each([
    ['down', "Frigate isn't answering, so its cameras can't be compared. You can still change a camera's settings."],
    [
      'safe_mode',
      'Frigate is in safe mode, with no cameras; see the Status page. You can still change a camera\'s settings.',
    ],
  ] as const)('explains Frigate being %s and keeps the settings editable', async (frigate, words) => {
    const unknown = cameraRow({ in_frigate: 'unknown', detect: null, zones_missing: null })
    const { wrapper } = await openPage(camerasState({ frigate, rows: [unknown] }))
    expect(wrapper.find('.v-alert').text()).toContain(words)
    expect(wrapper.text()).not.toContain('Zones')
    expect(wrapper.text()).not.toContain('Off in Frigate')
    expect(wrapper.text()).not.toContain('Frigate detection')
    expect(actionTexts(wrapper)).toEqual([])
    expect(await openRow(wrapper)).toBeTruthy()
  })

  it("shows the API's message when the cameras can't be loaded, and loads again on request", async () => {
    signedIn(ADMIN, { [CAMERAS]: apiError(500, 'config_unreadable', "config.yml couldn't be read.") })
    const { wrapper } = await mountApp('/cameras')
    expect(wrapper.find('.v-alert').text()).toContain("config.yml couldn't be read.")
    signedIn(ADMIN, { [CAMERAS]: camerasState() })
    await click(wrapper, 'Try again')
    expect(names(wrapper)).toEqual(['camera_1_3fa9c2'])
  })

  it("opens a row's settings in the row, one row at a time, and closes them on Cancel", async () => {
    const { wrapper } = await openPage()
    expect(openRows(wrapper)).toHaveLength(0)
    const form = await openRow(wrapper, 0)
    expect(form.getAttribute('aria-label')).toBe('Settings for camera_1_3fa9c2')
    expect(document.querySelector('.v-dialog')).toBeNull()
    await openRow(wrapper, 1)
    expect(openRows(wrapper)).toHaveLength(1)
    expect(rowItems(wrapper)[1].classes()).toContain('v-expansion-panel--active')
    await clickIn(rowItems(wrapper)[1].element, 'Cancel')
    expect(openRows(wrapper)).toHaveLength(0)
  })

  it("labels each row's header with what it opens", async () => {
    const { wrapper } = await openPage(camerasState({ rows: [WIDE, newRow()] }))
    const titles = wrapper.findAll('.v-expansion-panel-title').map((title) => title.text())
    expect(titles[0]).toContain('Settings')
    expect(titles[1]).toContain('Add as new')
    expect(titles[1]).not.toContain('Settings')
  })

  it('replaces the page with the state a save answers, and closes the row', async () => {
    const saved = camerasState({ rows: [{ ...WIDE, enabled: false }, TELE] })
    const { api, wrapper } = await openPage(undefined, { 'PUT /api/v1/cameras/camera_1_3fa9c2': saved })
    const form = await openRow(wrapper)
    // Switch Database capture off, then Save
    fieldIn(form, 'Database capture').click()
    await flushPromises()
    await clickIn(form, 'Save')
    const put = api.sent.find((request) => request.method === 'PUT')!
    expect(put.body).toEqual({ enabled: false, camera_radar: null, plate_recognizer: null })
    expect(openRows(wrapper)).toHaveLength(0)
    expect(wrapper.text()).toContain('Database capture: off')
    expect(api.sent.some((request) => request.path.endsWith('/frigate-detection'))).toBe(false)
  })

  it("sets Frigate's detection after the settings when it was switched, and shows the state it answers", async () => {
    const detected = camerasState({ rows: [{ ...WIDE, detect: false }, TELE] })
    const { api, wrapper } = await openPage(undefined, {
      'PUT /api/v1/cameras/camera_1_3fa9c2': camerasState({ rows: [WIDE, TELE] }),
      'PUT /api/v1/cameras/camera_1_3fa9c2/frigate-detection': detected,
    })
    const form = await openRow(wrapper)
    fieldIn(form, 'Frigate detection').click()
    await flushPromises()
    await clickIn(form, 'Save')
    const puts = api.sent.filter((request) => request.method === 'PUT')
    expect(puts.map((request) => request.path)).toEqual([
      '/api/v1/cameras/camera_1_3fa9c2',
      '/api/v1/cameras/camera_1_3fa9c2/frigate-detection',
    ])
    expect(puts[1].body).toEqual({ enabled: false })
    expect(openRows(wrapper)).toHaveLength(0)
    expect(rowItems(wrapper)[0].text()).toContain('Frigate detection: off')
  })

  it("keeps the row open with Frigate's refusal when the detection switch fails", async () => {
    const { wrapper } = await openPage(undefined, {
      'PUT /api/v1/cameras/camera_1_3fa9c2': camerasState({ rows: [WIDE, TELE] }),
      'PUT /api/v1/cameras/camera_1_3fa9c2/frigate-detection': apiError(
        502, 'frigate_error', "Frigate didn't take the change. Try again, or use Frigate's own switch.",
      ),
    })
    const form = await openRow(wrapper)
    fieldIn(form, 'Frigate detection').click()
    await flushPromises()
    await clickIn(form, 'Save')
    expect(openRows(wrapper)).toHaveLength(1)
    expect(form.textContent).toContain("Frigate didn't take the change.")
  })

  it('shows a refused radar under the Radar field and keeps the row open', async () => {
    const refused = json(422, {
      error: {
        code: 'validation',
        message: 'Choose a radar that config.yml lists, or no radar.',
        detail: { field: 'camera_radar' },
      },
    })
    const { wrapper } = await openPage(undefined, { 'PUT /api/v1/cameras/camera_1_3fa9c2': refused })
    const form = await openRow(wrapper)
    await clickIn(form, 'Save')
    expect(form.querySelector('.v-select .v-messages')!.textContent).toContain(
      'Choose a radar that config.yml lists, or no radar.',
    )
    expect(openRows(wrapper)).toHaveLength(1)
  })

  it('loads the page again when a save finds config.yml changed', async () => {
    const changed = apiError(409, 'config_changed', 'config.yml changed while you were editing. Try again.')
    const { api, wrapper } = await openPage(undefined, { 'PUT /api/v1/cameras/camera_1_3fa9c2': changed })
    const form = await openRow(wrapper)
    await clickIn(form, 'Save')
    expect(form.textContent).toContain('config.yml changed while you were editing')
    expect(api.sent.filter((request) => request.method === 'GET' && request.path === '/api/v1/cameras')).toHaveLength(2)
  })

  describe('actions', () => {
    const GONE = cameraRow({ in_frigate: 'absent', zones_missing: null, issues: [{ level: 'warn', code: 'gone' }] })
    const FRESH = newRow()
    const POINT = 'POST /api/v1/cameras/camera_1_3fa9c2/frigate-camera'
    const NEUTRAL = 'POST /api/v1/cameras/main_st/neutral-name'

    async function press(wrapper: VueWrapper, text: string) {
      const found = wrapper.findAll('button').filter((b) => b.text() === text)
      expect(found, `one button reading "${text}"`).toHaveLength(1)
      await found[0].trigger('click')
      await flushPromises()
    }

    it('offers a new row one Point button for each entry whose Frigate camera is gone', async () => {
      const { wrapper } = await openPage(camerasState({ rows: [GONE, FRESH] }))
      expect(actionTexts(wrapper)).toEqual(['Remove', 'Point camera_1_3fa9c2 at this'])
    })

    it('offers each of two new rows both gone entries', async () => {
      const goneToo = cameraRow({ name: 'camera_2_9d41e0', frigate_camera: 'main_st', in_frigate: 'absent' })
      const { wrapper } = await openPage(camerasState({ rows: [GONE, goneToo, FRESH, newRow('oak_ave_new')] }))
      const points = actionTexts(wrapper).filter((text) => text.startsWith('Point'))
      expect(points).toEqual([
        'Point camera_1_3fa9c2 at this',
        'Point camera_2_9d41e0 at this',
        'Point camera_1_3fa9c2 at this',
        'Point camera_2_9d41e0 at this',
      ])
    })

    it('has no buttons on a new row when no entry is gone', async () => {
      const { wrapper } = await openPage(camerasState({ rows: [WIDE, FRESH] }))
      expect(actionTexts(wrapper)).toEqual([])
    })

    it('confirms a point, posts the new Frigate camera, and shows the answer', async () => {
      const answer = camerasState({ rows: [{ ...WIDE, frigate_camera: 'oak_ave_tele' }] })
      const { api, wrapper } = await openPage(camerasState({ rows: [GONE, FRESH] }), { [POINT]: answer })
      await press(wrapper, 'Point camera_1_3fa9c2 at this')
      expect(dialogText()).toContain('Point camera_1_3fa9c2 at oak_ave_tele?')
      expect(dialogText()).toContain(
        'Events from oak_ave_tele will be recorded as camera_1_3fa9c2, with the same settings. ' +
          'Nothing already recorded changes.',
      )
      expect(api.sent.some((request) => request.method === 'POST')).toBe(false)
      await clickInDialog('Point')
      expect(api.sent.find((request) => request.method === 'POST')!.body).toEqual({ to: 'oak_ave_tele' })
      expect(names(wrapper)).toEqual(['camera_1_3fa9c2'])
      expect(wrapper.text()).toContain('Frigate: oak_ave_tele')
    })

    it('sends nothing when a confirm is cancelled', async () => {
      const { api, wrapper } = await openPage(camerasState({ rows: [GONE, FRESH] }))
      await press(wrapper, 'Point camera_1_3fa9c2 at this')
      await clickInDialog('Cancel')
      expect(api.sent.some((request) => request.method === 'POST')).toBe(false)
    })

    it('opens a new row to its add form, with capture on, no radar, and plates off, and posts on Add', async () => {
      const answer = camerasState({ rows: [WIDE, TELE] })
      const { api, wrapper } = await openPage(camerasState({ plates: true, rows: [WIDE, FRESH] }), {
        'POST /api/v1/cameras': answer,
      })
      const form = await openRow(wrapper, 1)
      expect(form.getAttribute('aria-label')).toBe('Add oak_ave_tele')
      expect(buttonsIn(form, 'Add')).toHaveLength(1)
      expect(buttonsIn(form, 'Save')).toHaveLength(0)
      expect(fieldIn(form, 'Database capture').checked).toBe(true)
      expect(fieldIn(form, 'Send plates to Plate Recognizer').checked).toBe(false)
      expect(form.querySelector('.v-select .v-select__selection')?.textContent?.trim()).toBe('No radar')
      await clickIn(form, 'Add')
      expect(api.sent.find((request) => request.method === 'POST')!.body).toEqual({
        frigate_camera: 'oak_ave_tele',
        enabled: true,
        camera_radar: null,
        plate_recognizer: false,
      })
      expect(names(wrapper)).toEqual(['camera_1_3fa9c2', 'camera_2_9d41e0'])
      expect(openRows(wrapper)).toHaveLength(0)
    })

    it('offers a name that is not a neutral name a neutral one, after a confirm', async () => {
      const hand = cameraRow({ name: 'main_st', frigate_camera: 'main_st', neutral: false })
      const answer = camerasState({ rows: [cameraRow({ name: 'camera_1_3fa9c2', frigate_camera: 'main_st' })] })
      const { api, wrapper } = await openPage(camerasState({ rows: [hand, WIDE] }), { [NEUTRAL]: answer })
      expect(actionTexts(wrapper).filter((text) => text === 'Use a neutral name')).toHaveLength(1)
      await press(wrapper, 'Use a neutral name')
      expect(dialogText()).toContain(
        'New records will be saved under a name like camera_1_3fa9c2 instead of main_st. ' +
          'Records already saved keep the name main_st, and the dashboards\' charts start again under the new name. ' +
          'A new deployment starts for this camera.',
      )
      await clickInDialog('Use a neutral name')
      const post = api.sent.find((request) => request.method === 'POST')!
      expect(post.path).toBe('/api/v1/cameras/main_st/neutral-name')
      expect(post.body).toBeNull()
      expect(names(wrapper)).toEqual(['camera_1_3fa9c2'])
    })

    it.each([
      ['gone', GONE, 'Frigate no longer has oak_ave_wide.'],
      [
        'duplicate',
        cameraRow({
          name: 'camera_2_9d41e0',
          duplicate_of: 'camera_1_3fa9c2',
          issues: [{ level: 'error', code: 'duplicate' }],
        }),
        'camera_1_3fa9c2 already records this Frigate camera.',
      ],
    ])('removes a %s entry after a confirm, in the error color', async (_kind, row, words) => {
      const answer = camerasState({ rows: [WIDE] })
      const { api, wrapper } = await openPage(camerasState({ rows: [row] }), {
        [`DELETE /api/v1/cameras/${row.name}`]: answer,
      })
      expect(wrapper.text()).toContain(words)
      await press(wrapper, 'Remove')
      expect(dialogText()).toContain(`Remove ${row.name}?`)
      expect(dialogText()).toContain('Its settings are removed from config.yml. Records already saved are kept.')
      expect(dialogButtons('Remove')[0].classList).toContain('bg-error')
      await clickInDialog('Remove')
      expect(api.sent.some((request) => request.method === 'DELETE')).toBe(true)
      expect(names(wrapper)).toEqual(['camera_1_3fa9c2'])
    })

    it('uses the primary color for the confirms that are not a removal', async () => {
      const { wrapper } = await openPage(camerasState({ rows: [GONE, FRESH] }))
      await press(wrapper, 'Point camera_1_3fa9c2 at this')
      expect(dialogButtons('Point')[0].classList).toContain('bg-primary')
      expect(dialogButtons('Point')[0].classList).not.toContain('bg-error')
    })

    it('offers no Remove for an entry that is in step, and no neutral name for a neutral one', async () => {
      const { wrapper } = await openPage(camerasState({ rows: [WIDE, TELE] }))
      expect(actionTexts(wrapper)).toEqual([])
    })

    it('shows the API message and loads the list again when an action finds Frigate or the file changed', async () => {
      const refused = apiError(409, 'cameras_changed', 'The cameras changed. Check the list and try again.')
      const { api, wrapper } = await openPage(camerasState({ rows: [GONE, FRESH] }), { [POINT]: refused })
      await press(wrapper, 'Point camera_1_3fa9c2 at this')
      await clickInDialog('Point')
      expect(wrapper.text()).toContain('The cameras changed. Check the list and try again.')
      expect(api.sent.filter((request) => request.method === 'GET' && request.path === '/api/v1/cameras')).toHaveLength(2)
    })

    it('shows the message and loads the list again when an action finds its camera gone', async () => {
      const missing = apiError(404, 'not_found', 'There is no such camera.')
      const { api, wrapper } = await openPage(camerasState({ rows: [GONE] }), {
        'DELETE /api/v1/cameras/camera_1_3fa9c2': missing,
      })
      await press(wrapper, 'Remove')
      await clickInDialog('Remove')
      expect(wrapper.text()).toContain('There is no such camera.')
      expect(api.sent.filter((request) => request.method === 'GET' && request.path === '/api/v1/cameras')).toHaveLength(2)
    })

    it('shows the API message for an action that fails some other way', async () => {
      const failed = apiError(500, 'oops', 'It failed.')
      const { wrapper } = await openPage(camerasState({ rows: [GONE] }), { 'DELETE /api/v1/cameras/camera_1_3fa9c2': failed })
      await press(wrapper, 'Remove')
      await clickInDialog('Remove')
      expect(wrapper.text()).toContain('It failed.')
    })

    it('closes the add form and says why when the Frigate camera was taken meanwhile', async () => {
      const refused = apiError(409, 'cameras_changed', 'Another entry already records that camera.')
      const before = camerasState({ rows: [WIDE, FRESH] })
      const after = camerasState({ rows: [WIDE, TELE] })
      let loads = 0
      const { api, wrapper } = await openPage(before, {
        [CAMERAS]: () => json(200, loads++ === 0 ? before : after),
        'POST /api/v1/cameras': refused,
      })
      const form = await openRow(wrapper, 1)
      await clickIn(form, 'Add')
      expect(openRows(wrapper)).toHaveLength(0)
      expect(wrapper.text()).toContain('Another entry already records that camera.')
      expect(names(wrapper)).toEqual(['camera_1_3fa9c2', 'camera_2_9d41e0'])
      expect(api.sent.filter((request) => request.method === 'GET' && request.path === '/api/v1/cameras')).toHaveLength(2)
    })

    it('offers no Point, Add, Remove, or neutral name while Frigate is down or in safe mode', async () => {
      const rows = [
        cameraRow({ name: 'main_st', frigate_camera: 'main_st', neutral: false, in_frigate: 'unknown', zones_missing: null }),
        newRow(),
      ]
      for (const frigate of ['down', 'safe_mode'] as const) {
        const { wrapper } = await openPage(camerasState({ frigate, rows }))
        expect(actionTexts(wrapper)).toEqual([])
        const titles = wrapper.findAll('.v-expansion-panel-title')
        expect(titles[0].text()).toContain('Settings')
        expect(titles[1].text()).not.toContain('Add as new')
        await titles[1].trigger('click')
        await flushPromises()
        expect(openRows(wrapper)).toHaveLength(0)
      }
    })
  })
})
