// The picker when the map's file can't be fetched: a page left open across an upgrade asks for a file that is gone.
// The first ask for PinMap.vue fails here, the second works.
import { flushPromises } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import MapPicker from '../src/modules/location/MapPicker.vue'
import { clickInDialog, dialogButtons, dialogText, mountAlone } from './mount'

const stub = vi.hoisted(() => ({ asks: 0, mounts: 0 }))

vi.mock('../src/modules/location/PinMap.vue', async () => {
  stub.asks += 1
  if (stub.asks === 1) throw new Error('Failed to fetch dynamically imported module')
  const { defineComponent, h, onMounted } = await import('vue')
  return {
    __esModule: true,
    default: defineComponent({
      emits: ['ready', 'failed', 'update:pin'],
      setup() {
        onMounted(() => (stub.mounts += 1))
        return () => h('div', { class: 'pin-map-stub' })
      },
    }),
  }
})

beforeEach(() => document.body.replaceChildren())

it('a map file that cannot be fetched says so, and Try again asks for it again', async () => {
  mountAlone(MapPicker, {
    open: true,
    styleUrl: 'https://tiles.example.invalid/style',
    start: null,
    centre: null,
  })
  await flushPromises()
  await flushPromises()
  expect(stub.mounts).toBe(0)
  expect(dialogText()).toContain(
    "The map couldn't load. This phone may have no internet connection. Type or paste the coordinates instead.",
  )
  expect(dialogButtons('Use this point')[0].disabled).toBe(true)

  await clickInDialog('Try again')
  await flushPromises()
  await flushPromises()
  expect(stub.asks).toBe(2)
  expect(stub.mounts).toBe(1)
  expect(document.querySelector('.pin-map-stub')).not.toBeNull()
  expect(dialogText()).not.toContain("The map couldn't load")
})
