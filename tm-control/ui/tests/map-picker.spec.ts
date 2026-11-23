// The picker dialog around the map. PinMap is stubbed: it can say it failed, and set the pin.
import { flushPromises } from '@vue/test-utils'
import { VDialog } from 'vuetify/components'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import MapPicker from '../src/modules/location/MapPicker.vue'
import { clickInDialog, dialogButtons, dialogText, mountAlone } from './mount'

const stub = vi.hoisted(() => ({ mounts: 0 }))

vi.mock('../src/modules/location/PinMap.vue', async () => {
  const { defineComponent, h, onMounted } = await import('vue')
  return {
    __esModule: true,
    default: defineComponent({
      props: { styleUrl: String, centre: Object, region: Object, pin: Object },
      emits: ['ready', 'failed', 'update:pin'],
      setup(props, { emit }) {
        onMounted(() => (stub.mounts += 1))
        return () =>
          h('div', { class: 'pin-map-stub', 'data-style': props.styleUrl, 'data-region': JSON.stringify(props.region ?? null) }, [
            h(
              'button',
              { type: 'button', onClick: () => emit('update:pin', { lat: 45.52252, lon: -122.6912 }) },
              'Drop the pin',
            ),
            h('button', { type: 'button', onClick: () => emit('failed') }, 'Fail the map'),
          ])
      },
    }),
  }
})

const STYLE = 'https://tiles.example.invalid/style'

function mountPicker(props: Record<string, unknown> = {}) {
  const wrapper = mountAlone(MapPicker, {
    open: true,
    styleUrl: STYLE,
    start: null,
    centre: null,
    region: null,
    'onUpdate:open': (value: boolean) => wrapper.setProps({ open: value }),
    ...props,
  })
  return wrapper
}

async function settle() {
  await flushPromises()
  await flushPromises()
}

describe('the map picker', () => {
  beforeEach(() => {
    document.body.replaceChildren()
    stub.mounts = 0
  })

  it('mounts nothing, so fetches nothing, before the dialog opens', async () => {
    mountPicker({ open: false })
    await settle()
    expect(stub.mounts).toBe(0)
    expect(document.querySelector('.pin-map-stub')).toBeNull()
  })

  it('names the host of the map and says the device sends nothing', async () => {
    mountPicker()
    await settle()
    expect(dialogText()).toContain('Pick the place on a map')
    expect(dialogText()).toContain(
      'The map comes from tiles.example.invalid. Your phone asks it for the area you look at; this device sends it nothing.',
    )
    expect(dialogText()).toContain('Tap the map to place the pin, then drag it to the exact spot.')
    expect(document.querySelector('.v-dialog')?.getAttribute('aria-label')).toBe('Pick the place on a map')
  })

  it('hands the region to the map, for when there is no point and no centre', async () => {
    mountPicker({ region: { lat: 34.05, lon: -118.24 } })
    await settle()
    expect(document.querySelector('.pin-map-stub')?.getAttribute('data-region')).toBe('{"lat":34.05,"lon":-118.24}')
  })

  it('Use this point is disabled until there is a pin, then answers with it', async () => {
    const wrapper = mountPicker()
    await settle()
    expect(dialogButtons('Use this point')[0].disabled).toBe(true)

    await clickInDialog('Drop the pin')
    expect(dialogText()).toContain('45.52252, -122.69120')
    expect(dialogText()).not.toContain('Tap the map to place the pin')
    expect(dialogButtons('Use this point')[0].disabled).toBe(false)

    await clickInDialog('Use this point')
    expect(wrapper.emitted('picked')).toEqual([[{ lat: 45.52252, lon: -122.6912 }]])
    expect((wrapper.props() as Record<string, unknown>).open).toBe(false)
  })

  it('starts at the point it was given, but only the map can make it the answer', async () => {
    const wrapper = mountPicker({ start: { lat: 45.0, lon: -122.0 } })
    await settle()
    expect(dialogText()).toContain('45.00000, -122.00000')
    // Nothing was picked: using the typed point would only write it back with more decimals than it has
    expect(dialogButtons('Use this point')[0].disabled).toBe(true)

    await clickInDialog('Drop the pin')
    expect(dialogButtons('Use this point')[0].disabled).toBe(false)
    await clickInDialog('Use this point')
    expect(wrapper.emitted('picked')).toEqual([[{ lat: 45.52252, lon: -122.6912 }]])
  })

  it('Use this point stays disabled while the map has failed', async () => {
    mountPicker({ start: { lat: 45.0, lon: -122.0 } })
    await settle()
    await clickInDialog('Drop the pin')
    expect(dialogButtons('Use this point')[0].disabled).toBe(false)
    await clickInDialog('Fail the map')
    expect(dialogButtons('Use this point')[0].disabled).toBe(true)
    await clickInDialog('Try again')
    await settle()
    // The pin the map set before it failed is still there
    expect(dialogButtons('Use this point')[0].disabled).toBe(false)
  })

  it('starts over, with Use this point disabled, each time it opens', async () => {
    const wrapper = mountPicker({ start: { lat: 45.0, lon: -122.0 } })
    await settle()
    await clickInDialog('Drop the pin')
    await clickInDialog('Cancel')
    await wrapper.setProps({ open: true })
    await settle()
    expect(dialogButtons('Use this point')[0].disabled).toBe(true)
  })

  it('a failure shows the message and Try again mounts the map again', async () => {
    mountPicker()
    await settle()
    expect(stub.mounts).toBe(1)

    await clickInDialog('Fail the map')
    expect(dialogText()).toContain(
      "The map couldn't load. This phone may have no internet connection. Type or paste the coordinates instead.",
    )
    expect(document.querySelector('.pin-map-stub')).toBeNull()
    expect(dialogText()).not.toContain('Tap the map') // there is no map to tap

    await clickInDialog('Try again')
    await settle()
    expect(stub.mounts).toBe(2)
    expect(document.querySelector('.pin-map-stub')).not.toBeNull()
    expect(dialogText()).not.toContain("The map couldn't load")
    expect(dialogText()).toContain('Tap the map to place the pin')
  })

  it('Cancel answers nothing', async () => {
    const wrapper = mountPicker()
    await settle()
    await clickInDialog('Drop the pin')
    await clickInDialog('Cancel')
    expect(wrapper.emitted('picked')).toBeUndefined()
    expect((wrapper.props() as Record<string, unknown>).open).toBe(false)
  })

  it('keeps the map while the dialog fades out and removes it after', async () => {
    const wrapper = mountPicker()
    await settle()
    await clickInDialog('Drop the pin')
    await clickInDialog('Cancel')
    expect((wrapper.props() as Record<string, unknown>).open).toBe(false)
    // The dialog is still fading: its body must not collapse by losing the map
    expect(document.querySelector('.pin-map-stub')).not.toBeNull()

    wrapper.findComponent(VDialog).vm.$emit('afterLeave')
    await settle()
    expect(document.querySelector('.pin-map-stub')).toBeNull()

    // Opening again mounts a map afresh
    await wrapper.setProps({ open: true })
    await settle()
    expect(stub.mounts).toBe(2)
    expect(document.querySelector('.pin-map-stub')).not.toBeNull()
  })

  it('starts over each time it opens', async () => {
    const wrapper = mountPicker()
    await settle()
    await clickInDialog('Drop the pin')
    await clickInDialog('Cancel')
    await wrapper.setProps({ open: true })
    await settle()
    expect(dialogText()).toContain('Tap the map to place the pin')
  })
})
