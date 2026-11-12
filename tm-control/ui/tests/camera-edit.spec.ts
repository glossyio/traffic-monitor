// The settings dialog: record, radar, and plates, and what it emits.
import { flushPromises } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CameraEdit from '../src/modules/cameras/CameraEdit.vue'
import { RADARS, cameraRow } from './fake-api'
import { clickInDialog, dialogField, dialogText, mountAlone } from './mount'

function mountEdit(props: Record<string, unknown> = {}) {
  return mountAlone(CameraEdit, { open: true, row: cameraRow(), radars: RADARS, plates: true, adding: false, ...props })
}

function emitted(wrapper: ReturnType<typeof mountEdit>, name: string) {
  return wrapper.emitted(name) ?? []
}

describe('CameraEdit', () => {
  it('has the three fields and the title', async () => {
    mountEdit()
    await flushPromises()
    expect(dialogText()).toContain('Settings for camera_1_3fa9c2')
    for (const label of ['Record events', 'Radar', 'Send plates to Plate Recognizer']) {
      expect(dialogField(label), label).toBeTruthy()
    }
  })

  it('has no plates switch when the add-on is not installed, and emits null for plates', async () => {
    const wrapper = mountEdit({ plates: false })
    await flushPromises()
    expect(dialogText()).not.toContain('Plate Recognizer')
    await clickInDialog('Save')
    expect(emitted(wrapper, 'save')[0]).toEqual([{ enabled: true, camera_radar: null, plate_recognizer: null }])
  })

  it("starts from the entry's settings and emits them unchanged on Save", async () => {
    const row = cameraRow({ enabled: false, camera_radar: 'TM_RADAR_SERIAL_PORT_00', plate_recognizer: true })
    const wrapper = mountEdit({ row })
    await flushPromises()
    await clickInDialog('Save')
    expect(emitted(wrapper, 'save')[0]).toEqual([
      { enabled: false, camera_radar: 'TM_RADAR_SERIAL_PORT_00', plate_recognizer: true },
    ])
  })

  it('emits the edited values', async () => {
    const wrapper = mountEdit()
    await flushPromises()
    dialogField('Record events').click()
    dialogField('Send plates to Plate Recognizer').click()
    await flushPromises()
    await clickInDialog('Save')
    expect(emitted(wrapper, 'save')[0]).toEqual([{ enabled: false, camera_radar: null, plate_recognizer: true }])
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
    expect(emitted(wrapper, 'save')[0]).toEqual([{ enabled: true, camera_radar: null, plate_recognizer: false }])
  })

  it('starts a new camera with record on, no radar, and no plates', async () => {
    const unset = cameraRow({ enabled: null, plate_recognizer: null })
    const wrapper = mountEdit({ row: unset, adding: true })
    await flushPromises()
    await clickInDialog('Save')
    expect(emitted(wrapper, 'save')[0]).toEqual([{ enabled: true, camera_radar: null, plate_recognizer: false }])
  })

  it('shows what the page passes for a refused radar and a failed save', async () => {
    mountEdit({ radarError: 'Choose a radar that config.yml lists, or no radar.', error: 'It failed.' })
    await flushPromises()
    expect(dialogText()).toContain('Choose a radar that config.yml lists, or no radar.')
    expect(dialogText()).toContain('It failed.')
  })

  it('emits cancel', async () => {
    const wrapper = mountEdit()
    await flushPromises()
    await clickInDialog('Cancel')
    expect(emitted(wrapper, 'cancel')).toHaveLength(1)
  })
})
