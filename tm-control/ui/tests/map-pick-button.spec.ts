// The button under the coordinates field that opens the map: absent when no map source is set, replaced by a sentence
// on the unit's own hotspot (which has no internet), otherwise "Pick on a map".
import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../src/api/schema'
import MapPickButton from '../src/modules/location/MapPickButton.vue'
import { useSession } from '../src/stores/session'
import { clickInDialog, dialogText, mountAlone } from './mount'

type MapSources = components['schemas']['MapSources']

vi.mock('../src/modules/location/PinMap.vue', async () => {
  const { defineComponent, h } = await import('vue')
  return {
    __esModule: true,
    default: defineComponent({
      props: { styleUrl: String, centre: Object, pin: Object },
      emits: ['ready', 'failed', 'update:pin'],
      setup(_props, { emit }) {
        return () =>
          h(
            'button',
            { type: 'button', onClick: () => emit('update:pin', { lat: 45.52252, lon: -122.6912 }) },
            'Drop the pin',
          )
      },
    }),
  }
})

const ON: MapSources = { style_url: 'https://tiles.example.invalid/style', overpass_url: null }
const OFF: MapSources = { style_url: null, overpass_url: 'https://street.example.invalid/api' }

const HOTSPOT_SENTENCE =
  "The map needs the internet, and this device's hotspot has none. Type or paste the coordinates, or come back to this page once the device is on your Wi-Fi."

function mountButton(map: MapSources, coordinates = '') {
  const wrapper = mountAlone(MapPickButton, {
    map,
    centre: null,
    coordinates,
    'onUpdate:coordinates': (value: string) => wrapper.setProps({ coordinates: value }),
  })
  return wrapper
}

// The session says the page came over the unit's hotspot (the store is the one the mounted component reads)
async function onHotspot() {
  useSession().status = { hotspot: { local_name: 'tm-fake.local' } } as never
  await flushPromises()
}

describe('the map pick button', () => {
  beforeEach(() => document.body.replaceChildren())

  it('no map source: nothing is shown', () => {
    const wrapper = mountButton(OFF)
    expect(wrapper.text()).toBe('')
    expect(wrapper.findAll('button')).toHaveLength(0)
  })

  it('on the hotspot: the sentence, and no button', async () => {
    const wrapper = mountButton(ON)
    expect(wrapper.findAll('button')).toHaveLength(1)
    await onHotspot()
    expect(wrapper.text()).toContain(HOTSPOT_SENTENCE)
    expect(wrapper.findAll('button')).toHaveLength(0)
  })

  it('no map source wins over the hotspot', async () => {
    const wrapper = mountButton(OFF)
    await onHotspot()
    expect(wrapper.text()).toBe('')
  })

  it('a picked point is written as "45.52252, -122.69120"', async () => {
    const wrapper = mountButton(ON)
    expect(wrapper.find('button').text()).toBe('Pick on a map')
    await wrapper.find('button').trigger('click')
    await flushPromises()
    await flushPromises()
    await clickInDialog('Drop the pin')
    expect(dialogText()).toContain('Pick the place on a map')
    await clickInDialog('Use this point')
    expect((wrapper.props() as Record<string, unknown>).coordinates).toBe('45.52252, -122.69120')
    expect(wrapper.emitted('picked')).toHaveLength(1)
  })

  it('the picker starts at the coordinates already in the field', async () => {
    const wrapper = mountButton(ON, '45.0, -122.0')
    await wrapper.find('button').trigger('click')
    await flushPromises()
    await flushPromises()
    expect(dialogText()).toContain('45.00000, -122.00000')
  })
})
