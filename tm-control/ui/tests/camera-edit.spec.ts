// The settings dialog: Frigate detection, database capture, radar, and plates, and what it emits.
import { flushPromises } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CameraEdit from '../src/modules/cameras/CameraEdit.vue'
import { RADARS, cameraRow, type CameraRadar } from './fake-api'
import { clickInDialog, dialogField, dialogText, mountAlone } from './mount'

function mountEdit(props: Record<string, unknown> = {}) {
  return mountAlone(CameraEdit, { open: true, row: cameraRow(), radars: RADARS, plates: true, frigate: true, adding: false, ...props })
}

function emitted(wrapper: ReturnType<typeof mountEdit>, name: string) {
  return wrapper.emitted(name) ?? []
}

describe('CameraEdit', () => {
  it('has the four fields and the title', async () => {
    mountEdit()
    await flushPromises()
    expect(dialogText()).toContain('Settings for camera_1_3fa9c2')
    for (const label of ['Frigate detection', 'Database capture', 'Radar', 'Send plates to Plate Recognizer']) {
      expect(dialogField(label), label).toBeTruthy()
    }
  })

  it('has no plates switch when the add-on is not installed, and emits null for plates', async () => {
    const wrapper = mountEdit({ plates: false })
    await flushPromises()
    expect(dialogText()).not.toContain('Plate Recognizer')
    await clickInDialog('Save')
    expect(emitted(wrapper, 'save')[0]).toEqual([{ enabled: true, camera_radar: null, plate_recognizer: null }, null])
  })

  it("starts from the entry's settings and emits them unchanged on Save", async () => {
    const row = cameraRow({ enabled: false, camera_radar: 'TM_RADAR_SERIAL_PORT_00', plate_recognizer: true })
    const wrapper = mountEdit({ row })
    await flushPromises()
    await clickInDialog('Save')
    expect(emitted(wrapper, 'save')[0]).toEqual([
      { enabled: false, camera_radar: 'TM_RADAR_SERIAL_PORT_00', plate_recognizer: true },
      null,
    ])
  })

  it('emits the edited values', async () => {
    const wrapper = mountEdit()
    await flushPromises()
    dialogField('Database capture').click()
    dialogField('Send plates to Plate Recognizer').click()
    await flushPromises()
    await clickInDialog('Save')
    expect(emitted(wrapper, 'save')[0]).toEqual([{ enabled: false, camera_radar: null, plate_recognizer: true }, null])
  })

  it('emits a chosen radar, and null again for No radar', async () => {
    const wrapper = mountEdit({ row: cameraRow({ camera_radar: 'TM_RADAR_SERIAL_PORT_00' }) })
    await flushPromises()
    // Open the drop-down and choose No radar
    dialogField('Radar').dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    await flushPromises()
    const none = [...document.querySelectorAll<HTMLElement>('.v-overlay-container .v-list-item')].find(
      (item) => item.textContent?.trim() === 'No radar',
    )!
    none.click()
    await flushPromises()
    await clickInDialog('Save')
    expect(emitted(wrapper, 'save')[0]).toEqual([{ enabled: true, camera_radar: null, plate_recognizer: false }, null])
  })

  it('shows No radar in the closed field when the camera has no radar', async () => {
    mountEdit({ row: cameraRow({ camera_radar: null }) })
    await flushPromises()
    const field = document.querySelector('.v-dialog .v-select .v-select__selection')
    expect(field?.textContent?.trim()).toBe('No radar')
  })

  it("shows each radar's state in the drop-down and can't choose one config.yml doesn't set up", async () => {
    const radars: CameraRadar[] = [
      { name: 'R_ON', in_config: true, enabled: true, port_open: true },
      { name: 'R_OFF', in_config: true, enabled: false, port_open: true },
      { name: 'R_CLOSED', in_config: true, enabled: true, port_open: false },
      { name: 'R_UNSET', in_config: false, enabled: false, port_open: null },
    ]
    mountEdit({ radars })
    await flushPromises()
    dialogField('Radar').dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    await flushPromises()
    const item = (name: string) =>
      [...document.querySelectorAll<HTMLElement>('.v-overlay-container .v-list-item')].find((node) =>
        node.querySelector('.v-list-item-title')?.textContent?.trim() === name,
      )!
    expect(item('R_OFF').textContent).toContain('off in config.yml')
    expect(item('R_CLOSED').textContent).toContain('port closed')
    expect(item('R_UNSET').textContent).toContain('not set up in config.yml')
    expect(item('R_UNSET').classList).toContain('v-list-item--disabled')
    expect(item('R_ON').classList).not.toContain('v-list-item--disabled')
    expect(item('R_OFF').classList).not.toContain('v-list-item--disabled')
  })

  it('starts a new camera with record on, no radar, and no plates', async () => {
    const unset = cameraRow({ enabled: null, plate_recognizer: null })
    const wrapper = mountEdit({ row: unset, adding: true })
    await flushPromises()
    expect(dialogText()).toContain('Add oak_ave_wide')
    expect(dialogText()).not.toContain('Settings for')
    await clickInDialog('Add')
    expect(emitted(wrapper, 'save')[0]).toEqual([{ enabled: true, camera_radar: null, plate_recognizer: false }, null])
  })

  it('shows what the page passes for a refused radar and a failed save', async () => {
    mountEdit({ radarError: 'Choose a radar that config.yml lists, or no radar.', error: 'It failed.' })
    await flushPromises()
    expect(dialogText()).toContain('Choose a radar that config.yml lists, or no radar.')
    expect(dialogText()).toContain('It failed.')
  })

  it("starts Frigate detection from Frigate's switch and emits it only when it changes", async () => {
    const wrapper = mountEdit({ row: cameraRow({ detect: false }) })
    await flushPromises()
    expect(dialogField('Frigate detection').checked).toBe(false)
    expect(dialogText()).toContain("Changes Frigate's own switch for this camera, at once.")
    await clickInDialog('Save')
    dialogField('Frigate detection').click()
    await flushPromises()
    await clickInDialog('Save')
    expect(emitted(wrapper, 'save')).toEqual([
      [{ enabled: true, camera_radar: null, plate_recognizer: false }, null],
      [{ enabled: true, camera_radar: null, plate_recognizer: false }, true],
    ])
  })

  it.each([
    ['while adding', { adding: true }],
    ["while Frigate doesn't answer", { frigate: false }],
    ['for a camera that is off in Frigate', { row: cameraRow({ in_frigate: 'off', detect: false }) }],
    ['for a camera Frigate no longer has', { row: cameraRow({ in_frigate: 'absent', detect: null }) }],
  ])('has no Frigate detection switch %s', async (_, props) => {
    mountEdit(props)
    await flushPromises()
    expect(dialogText()).not.toContain('Frigate detection')
    expect(dialogField('Database capture')).toBeTruthy()
  })

  it('emits cancel', async () => {
    const wrapper = mountEdit()
    await flushPromises()
    await clickInDialog('Cancel')
    expect(emitted(wrapper, 'cancel')).toHaveLength(1)
  })
})
