// The Cameras page: one row per camera, the intro, Frigate's state, and the settings dialog's save.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CameraEdit from '../src/modules/cameras/CameraEdit.vue'
import { ADMIN, apiError, camerasState, cameraRow, json, newRow, signedIn } from './fake-api'
import { click, clickInDialog, dialogButtons, dialogField, dialogText, mountApp } from './mount'

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

function names(wrapper: VueWrapper) {
  return wrapper.findAll('.v-list .font-weight-bold').map((node) => node.text())
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
    expect(wrapper.find('a[href="/frigate/"]').exists()).toBe(true)
  })

  it("shows each camera's settings and zones", async () => {
    const { wrapper } = await openPage()
    const text = wrapper.text()
    expect(text).toContain('Zones: all four')
    expect(text).toContain('Missing in Frigate: zone_near, zone_far')
    expect(text).toContain('Radar: TM_RADAR_SERIAL_PORT_00')
    expect(text).toContain('Radar: none')
    expect(text).toContain('Record events: on')
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
          cameraRow({ in_frigate: 'absent', zones_missing: null }),
          cameraRow({ name: 'camera_2_9d41e0', duplicate_of: 'camera_1_3fa9c2' }),
        ],
      }),
    )
    expect(wrapper.text()).toContain('Frigate no longer has oak_ave_wide.')
    expect(wrapper.text()).toContain('camera_1_3fa9c2 already records this Frigate camera.')
  })

  it('lists a Frigate camera that no entry points at as not recorded, without an Edit button', async () => {
    const { wrapper } = await openPage(camerasState({ rows: [WIDE, newRow()] }))
    expect(wrapper.text()).toContain("oak_ave_tele is new in Frigate and isn't recorded.")
    expect(wrapper.findAll('button').filter((b) => b.text() === 'Edit')).toHaveLength(1)
  })

  it.each([
    ['down', "Frigate isn't answering, so its cameras can't be compared. You can still change a camera's settings."],
    [
      'safe_mode',
      'Frigate is in safe mode, with no cameras; see the Status page. You can still change a camera\'s settings.',
    ],
  ] as const)('explains Frigate being %s and keeps the settings editable', async (frigate, words) => {
    const unknown = cameraRow({ in_frigate: 'unknown', zones_missing: null })
    const { wrapper } = await openPage(camerasState({ frigate, rows: [unknown] }))
    expect(wrapper.find('.v-alert').text()).toContain(words)
    expect(wrapper.text()).not.toContain('Zones')
    expect(wrapper.text()).not.toContain('Off in Frigate')
    const buttons = wrapper.findAll('button').map((b) => b.text())
    expect(buttons).toContain('Edit')
    expect(buttons.filter((text) => text !== 'Edit')).toEqual([])
  })

  it("shows the API's message when the cameras can't be loaded, and loads again on request", async () => {
    signedIn(ADMIN, { [CAMERAS]: apiError(500, 'config_unreadable', "config.yml couldn't be read.") })
    const { wrapper } = await mountApp('/cameras')
    expect(wrapper.find('.v-alert').text()).toContain("config.yml couldn't be read.")
    signedIn(ADMIN, { [CAMERAS]: camerasState() })
    await click(wrapper, 'Try again')
    expect(names(wrapper)).toEqual(['camera_1_3fa9c2'])
  })

  it('opens the settings dialog on Edit and replaces the page with the state a save answers', async () => {
    const saved = camerasState({ rows: [{ ...WIDE, enabled: false }, TELE] })
    const { api, wrapper } = await openPage(undefined, { 'PUT /api/v1/cameras/camera_1_3fa9c2': saved })
    await wrapper.findAll('button').filter((b) => b.text() === 'Edit')[0].trigger('click')
    await flushPromises()
    expect(dialogText()).toContain('Settings for camera_1_3fa9c2')
    expect(dialogButtons('Save')).toHaveLength(1)
    // Switch Record events off, then Save
    const toggle = document.querySelector<HTMLInputElement>('.v-dialog input[type="checkbox"]')!
    toggle.click()
    await flushPromises()
    await clickInDialog('Save')
    const put = api.sent.find((request) => request.method === 'PUT')!
    expect(put.body).toEqual({ enabled: false, camera_radar: null, plate_recognizer: null })
    expect(wrapper.findComponent(CameraEdit).props('open')).toBe(false)
    expect(wrapper.text()).toContain('Record events: off')
  })

  it('shows a refused radar under the Radar field and keeps the dialog open', async () => {
    const refused = json(422, {
      error: {
        code: 'validation',
        message: 'Choose a radar that config.yml lists, or no radar.',
        detail: { field: 'camera_radar' },
      },
    })
    const { wrapper } = await openPage(undefined, { 'PUT /api/v1/cameras/camera_1_3fa9c2': refused })
    await wrapper.findAll('button').filter((b) => b.text() === 'Edit')[0].trigger('click')
    await flushPromises()
    await clickInDialog('Save')
    const dialog = document.querySelector('.v-dialog')!
    expect(dialog.querySelector('.v-select .v-messages')!.textContent).toContain(
      'Choose a radar that config.yml lists, or no radar.',
    )
    expect(dialogButtons('Save')).toHaveLength(1)
  })

  it('loads the page again when a save finds config.yml changed', async () => {
    const changed = apiError(409, 'config_changed', 'config.yml changed while you were editing. Try again.')
    const { api, wrapper } = await openPage(undefined, { 'PUT /api/v1/cameras/camera_1_3fa9c2': changed })
    await wrapper.findAll('button').filter((b) => b.text() === 'Edit')[0].trigger('click')
    await flushPromises()
    await clickInDialog('Save')
    expect(dialogText()).toContain('config.yml changed while you were editing')
    expect(api.sent.filter((request) => request.method === 'GET' && request.path === '/api/v1/cameras')).toHaveLength(2)
  })

  describe('actions', () => {
    const GONE = cameraRow({ in_frigate: 'absent', zones_missing: null })
    const FRESH = newRow()
    const POINT = 'POST /api/v1/cameras/camera_1_3fa9c2/frigate-camera'
    const NEUTRAL = 'POST /api/v1/cameras/main_st/neutral-name'

    function buttonTexts(wrapper: VueWrapper) {
      return wrapper.findAll('button').map((b) => b.text())
    }

    async function press(wrapper: VueWrapper, text: string) {
      const found = wrapper.findAll('button').filter((b) => b.text() === text)
      expect(found, `one button reading "${text}"`).toHaveLength(1)
      await found[0].trigger('click')
      await flushPromises()
    }

    it('offers a new row one Point button for each entry whose Frigate camera is gone, and Add as new', async () => {
      const { wrapper } = await openPage(camerasState({ rows: [GONE, FRESH] }))
      expect(buttonTexts(wrapper)).toEqual(['Edit', 'Remove', 'Point camera_1_3fa9c2 at this', 'Add as new'])
    })

    it('offers each of two new rows both gone entries', async () => {
      const goneToo = cameraRow({ name: 'camera_2_9d41e0', frigate_camera: 'main_st', in_frigate: 'absent' })
      const { wrapper } = await openPage(camerasState({ rows: [GONE, goneToo, FRESH, newRow('oak_ave_new')] }))
      const points = buttonTexts(wrapper).filter((text) => text.startsWith('Point'))
      expect(points).toEqual([
        'Point camera_1_3fa9c2 at this',
        'Point camera_2_9d41e0 at this',
        'Point camera_1_3fa9c2 at this',
        'Point camera_2_9d41e0 at this',
      ])
    })

    it('has only Add as new for a new row when no entry is gone', async () => {
      const { wrapper } = await openPage(camerasState({ rows: [WIDE, FRESH] }))
      expect(buttonTexts(wrapper)).toEqual(['Edit', 'Add as new'])
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

    it('opens the add dialog with record on, no radar, and plates off, and posts on Add', async () => {
      const answer = camerasState({ rows: [WIDE, TELE] })
      const { api, wrapper } = await openPage(camerasState({ plates: true, rows: [WIDE, FRESH] }), {
        'POST /api/v1/cameras': answer,
      })
      await press(wrapper, 'Add as new')
      expect(dialogText()).toContain('Add oak_ave_tele')
      expect(dialogButtons('Add')).toHaveLength(1)
      expect(dialogButtons('Save')).toHaveLength(0)
      expect(dialogField('Record events').checked).toBe(true)
      expect(dialogField('Send plates to Plate Recognizer').checked).toBe(false)
      expect(document.querySelector('.v-dialog .v-select .v-select__selection')?.textContent?.trim()).toBe('No radar')
      await clickInDialog('Add')
      expect(api.sent.find((request) => request.method === 'POST')!.body).toEqual({
        frigate_camera: 'oak_ave_tele',
        enabled: true,
        camera_radar: null,
        plate_recognizer: false,
      })
      expect(names(wrapper)).toEqual(['camera_1_3fa9c2', 'camera_2_9d41e0'])
      expect(wrapper.findComponent(CameraEdit).exists()).toBe(false)
    })

    it('offers a name that is not a neutral name a neutral one, after a confirm', async () => {
      const hand = cameraRow({ name: 'main_st', frigate_camera: 'main_st', neutral: false })
      const answer = camerasState({ rows: [cameraRow({ name: 'camera_1_3fa9c2', frigate_camera: 'main_st' })] })
      const { api, wrapper } = await openPage(camerasState({ rows: [hand, WIDE] }), { [NEUTRAL]: answer })
      expect(buttonTexts(wrapper).filter((text) => text === 'Use a neutral name')).toHaveLength(1)
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
        cameraRow({ name: 'camera_2_9d41e0', duplicate_of: 'camera_1_3fa9c2' }),
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
      expect(buttonTexts(wrapper)).toEqual(['Edit', 'Edit'])
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

    it('closes the add dialog and says why when the Frigate camera was taken meanwhile', async () => {
      const refused = apiError(409, 'cameras_changed', 'Another entry already records that camera.')
      const before = camerasState({ rows: [WIDE, FRESH] })
      const after = camerasState({ rows: [WIDE, TELE] })
      let loads = 0
      const { api, wrapper } = await openPage(before, {
        [CAMERAS]: () => json(200, loads++ === 0 ? before : after),
        'POST /api/v1/cameras': refused,
      })
      await press(wrapper, 'Add as new')
      await clickInDialog('Add')
      expect(dialogButtons('Add')).toHaveLength(0)
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
        expect(buttonTexts(wrapper)).toEqual(['Edit'])
      }
    })
  })
})
