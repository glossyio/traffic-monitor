// The Cameras page: one row per camera, the intro, Frigate's state, and the settings dialog's save.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CameraEdit from '../src/modules/cameras/CameraEdit.vue'
import { ADMIN, apiError, camerasState, cameraRow, json, signedIn } from './fake-api'
import { click, clickInDialog, dialogButtons, dialogText, mountApp } from './mount'

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
    expect(wrapper.text()).toContain('Not in Frigate')
    expect(wrapper.text()).toContain('Same Frigate camera as camera_1_3fa9c2')
  })

  it('lists a Frigate camera that no entry points at as not recorded, without an Edit button', async () => {
    const unpointed = cameraRow({
      name: null,
      frigate_camera: 'oak_ave_tele',
      neutral: null,
      enabled: null,
      zones_missing: [],
    })
    const { wrapper } = await openPage(camerasState({ rows: [WIDE, unpointed] }))
    expect(wrapper.text()).toContain('oak_ave_tele')
    expect(wrapper.text()).toContain('Not recorded')
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
})
