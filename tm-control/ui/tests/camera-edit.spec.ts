// A camera's settings form, shown inside its row: Frigate detection, database capture, radar, and plates, and what it
// emits.
import { flushPromises } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import CameraEdit from '../src/modules/cameras/CameraEdit.vue'
import { RADARS, cameraRow, type CameraRadar } from './fake-api'
import { buttonsIn, clickIn, fieldIn, mountAlone } from './mount'

function mountEdit(props: Record<string, unknown> = {}) {
  const wrapper = mountAlone(CameraEdit, {
    open: true,
    row: cameraRow(),
    radars: RADARS,
    plates: true,
    frigate: true,
    adding: false,
    ...props,
  })
  const form = wrapper.element as Element
  return {
    wrapper,
    field: (label: string) => fieldIn(form, label),
    click: (text: string) => clickIn(form, text),
    emitted: (name: string) => wrapper.emitted(name) ?? [],
  }
}

describe('CameraEdit', () => {
  it('is a form in the page, named for its camera, with the four fields', async () => {
    const { wrapper, field } = mountEdit()
    await flushPromises()
    expect(document.querySelector('.v-dialog')).toBeNull()
    expect(wrapper.find('form').attributes('aria-label')).toBe('Settings for camera_1_3fa9c2')
    for (const label of ['Frigate detection', 'Database capture', 'Radar', 'Send plates to Plate Recognizer']) {
      expect(field(label), label).toBeTruthy()
    }
  })

  it('has no plates switch when the add-on is not installed, and emits null for plates', async () => {
    const { wrapper, click, emitted } = mountEdit({ plates: false })
    await flushPromises()
    expect(wrapper.text()).not.toContain('Plate Recognizer')
    await click('Save')
    expect(emitted('save')[0]).toEqual([{ enabled: true, camera_radar: null, plate_recognizer: null }, null])
  })

  it("starts from the entry's settings and emits them unchanged on Save", async () => {
    const row = cameraRow({ enabled: false, camera_radar: 'TM_RADAR_SERIAL_PORT_00', plate_recognizer: true })
    const { click, emitted } = mountEdit({ row })
    await flushPromises()
    await click('Save')
    expect(emitted('save')[0]).toEqual([
      { enabled: false, camera_radar: 'TM_RADAR_SERIAL_PORT_00', plate_recognizer: true },
      null,
    ])
  })

  it('emits the edited values', async () => {
    const { field, click, emitted } = mountEdit()
    await flushPromises()
    field('Database capture').click()
    field('Send plates to Plate Recognizer').click()
    await flushPromises()
    await click('Save')
    expect(emitted('save')[0]).toEqual([{ enabled: false, camera_radar: null, plate_recognizer: true }, null])
  })

  it('emits a chosen radar, and null again for No radar', async () => {
    const { field, click, emitted } = mountEdit({ row: cameraRow({ camera_radar: 'TM_RADAR_SERIAL_PORT_00' }) })
    await flushPromises()
    // Open the drop-down and choose No radar
    field('Radar').dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    await flushPromises()
    const none = [...document.querySelectorAll<HTMLElement>('.v-overlay-container .v-list-item')].find(
      (item) => item.textContent?.trim() === 'No radar',
    )!
    none.click()
    await flushPromises()
    await click('Save')
    expect(emitted('save')[0]).toEqual([{ enabled: true, camera_radar: null, plate_recognizer: false }, null])
  })

  it('shows No radar in the closed field when the camera has no radar', async () => {
    const { wrapper } = mountEdit({ row: cameraRow({ camera_radar: null }) })
    await flushPromises()
    expect(wrapper.find('.v-select .v-select__selection').text()).toBe('No radar')
  })

  it("shows each radar's state in the drop-down and can't choose one config.yml doesn't set up", async () => {
    const radars: CameraRadar[] = [
      { name: 'R_ON', in_config: true, enabled: true, port_open: true },
      { name: 'R_OFF', in_config: true, enabled: false, port_open: true },
      { name: 'R_CLOSED', in_config: true, enabled: true, port_open: false },
      { name: 'R_UNSET', in_config: false, enabled: false, port_open: null },
    ]
    const { field } = mountEdit({ radars })
    await flushPromises()
    field('Radar').dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
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

  it('starts a new camera with capture on, no radar, and no plates, and reads Add', async () => {
    const unset = cameraRow({ enabled: null, plate_recognizer: null })
    const { wrapper, click, emitted } = mountEdit({ row: unset, adding: true })
    await flushPromises()
    expect(wrapper.find('form').attributes('aria-label')).toBe('Add oak_ave_wide')
    expect(buttonsIn(wrapper.element, 'Save')).toHaveLength(0)
    await click('Add')
    expect(emitted('save')[0]).toEqual([{ enabled: true, camera_radar: null, plate_recognizer: false }, null])
  })

  it('shows what the page passes for a refused radar and a failed save', async () => {
    const { wrapper } = mountEdit({ radarError: 'Choose a radar that config.yml lists, or no radar.', error: 'It failed.' })
    await flushPromises()
    expect(wrapper.text()).toContain('Choose a radar that config.yml lists, or no radar.')
    expect(wrapper.text()).toContain('It failed.')
  })

  it("starts Frigate detection from Frigate's switch and emits it only when it changes", async () => {
    const { wrapper, field, click, emitted } = mountEdit({ row: cameraRow({ detect: false }) })
    await flushPromises()
    expect(field('Frigate detection').checked).toBe(false)
    expect(wrapper.text()).toContain("Changes Frigate's own switch for this camera when you save.")
    await click('Save')
    field('Frigate detection').click()
    await flushPromises()
    await click('Save')
    expect(emitted('save')).toEqual([
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
    const { wrapper, field } = mountEdit(props)
    await flushPromises()
    expect(wrapper.text()).not.toContain('Frigate detection')
    expect(field('Database capture')).toBeTruthy()
  })

  it('emits cancel and closes', async () => {
    const { click, emitted } = mountEdit()
    await flushPromises()
    await click('Cancel')
    expect(emitted('cancel')).toHaveLength(1)
    expect(emitted('update:open')).toEqual([[false]])
  })

  it('starts over from the row each time it opens', async () => {
    const { wrapper, field } = mountEdit()
    await flushPromises()
    field('Database capture').click()
    await flushPromises()
    expect(field('Database capture').checked).toBe(false)
    await wrapper.setProps({ open: false })
    await wrapper.setProps({ open: true })
    expect(field('Database capture').checked).toBe(true)
  })
})
