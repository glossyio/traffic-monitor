// The map inside the picker: the only code that talks to MapLibre. The library is faked here with classes that record
// what PinMap asks of them, so no WebGL, worker, or network is needed.
import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import PinMap from '../src/modules/location/PinMap.vue'
import { mountAlone } from './mount'

type Handler = (event?: unknown) => void

const fake = vi.hoisted(() => {
  class FakeMap {
    static all: FakeMap[] = []
    static failWith: Error | null = null // the constructor throws this, as MapLibre does with no WebGL2
    static failAfter: Error | null = null // a call after the constructor throws this
    options: Record<string, unknown>
    handlers: Record<string, Handler[]> = {}
    controls: { control: unknown; position?: string }[] = []
    removed = false
    touchZoomRotate = { disableRotation: vi.fn() }
    keyboard = { disableRotation: vi.fn() }
    constructor(options: Record<string, unknown>) {
      if (FakeMap.failWith) throw FakeMap.failWith
      this.options = options
      FakeMap.all.push(this)
    }
    on(type: string, handler: Handler) {
      ;(this.handlers[type] ??= []).push(handler)
      return this
    }
    addControl(control: unknown, position?: string) {
      if (FakeMap.failAfter) throw FakeMap.failAfter
      this.controls.push({ control, position })
      return this
    }
    remove() {
      this.removed = true
    }
    fire(type: string, event?: unknown) {
      for (const handler of this.handlers[type] ?? []) handler(event)
    }
  }
  class FakeMarker {
    static all: FakeMarker[] = []
    options: Record<string, unknown>
    handlers: Record<string, Handler[]> = {}
    lngLat: [number, number] | null = null
    element = document.createElement('div')
    map: FakeMap | null = null
    removed = false
    constructor(options: Record<string, unknown>) {
      this.options = options
      FakeMarker.all.push(this)
    }
    setLngLat(value: [number, number]) {
      this.lngLat = value
      return this
    }
    getLngLat() {
      return { lng: this.lngLat![0], lat: this.lngLat![1] }
    }
    getElement() {
      return this.element
    }
    addTo(map: FakeMap) {
      this.map = map
      return this
    }
    on(type: string, handler: Handler) {
      ;(this.handlers[type] ??= []).push(handler)
      return this
    }
    remove() {
      this.removed = true
    }
    fire(type: string) {
      for (const handler of this.handlers[type] ?? []) handler()
    }
  }
  class FakeNavigationControl {
    options: Record<string, unknown>
    constructor(options: Record<string, unknown>) {
      this.options = options
    }
  }
  return { FakeMap, FakeMarker, FakeNavigationControl, setWorkerUrl: vi.fn() }
})

vi.mock('maplibre-gl', () => ({
  Map: fake.FakeMap,
  Marker: fake.FakeMarker,
  NavigationControl: fake.FakeNavigationControl,
  setWorkerUrl: fake.setWorkerUrl,
}))

const STYLE = 'https://tiles.example.invalid/style'
const LATLON = { lat: 45.52252, lon: -122.6912 }

type Pin = { lat: number; lon: number } | null

function mountMap(props: { centre?: Pin; pin?: Pin; region?: Pin } = {}) {
  const wrapper = mountAlone(PinMap, {
    styleUrl: STYLE,
    centre: props.centre ?? null,
    region: props.region ?? null,
    pin: props.pin ?? null,
    'onUpdate:pin': (value: Pin) => wrapper.setProps({ pin: value }),
  })
  return wrapper
}

function theMap() {
  expect(fake.FakeMap.all).toHaveLength(1)
  return fake.FakeMap.all[0]
}

describe('the pin map', () => {
  beforeEach(() => {
    document.body.replaceChildren()
    fake.FakeMap.all.length = 0
    fake.FakeMarker.all.length = 0
    fake.setWorkerUrl.mockClear()
  })

  it('opens at the pin at zoom 17, else the centre at 14, else the world', () => {
    mountMap({ pin: LATLON, centre: { lat: 45.0, lon: -122.0 } })
    expect(theMap().options).toMatchObject({ style: STYLE, center: [-122.6912, 45.52252], zoom: 17 })
    expect(fake.FakeMarker.all).toHaveLength(1)
    expect(fake.FakeMarker.all[0].lngLat).toEqual([-122.6912, 45.52252])
    expect(fake.setWorkerUrl).toHaveBeenCalledWith(expect.any(String))

    fake.FakeMap.all.length = 0
    mountMap({ centre: { lat: 45.0, lon: -122.0 } })
    expect(theMap().options).toMatchObject({ center: [-122.0, 45.0], zoom: 14 })

    fake.FakeMap.all.length = 0
    mountMap()
    expect(theMap().options).toMatchObject({ center: [0, 20], zoom: 1 })
    expect(fake.FakeMarker.all).toHaveLength(1) // only the first mount had a pin
  })

  it('with no pin and no centre, opens over the region at zoom 3; a centre or a pin wins over it', () => {
    const region = { lat: 34.05, lon: -118.24 }
    mountMap({ region })
    expect(theMap().options).toMatchObject({ center: [-118.24, 34.05], zoom: 3 })
    expect(fake.FakeMarker.all).toHaveLength(0) // a region is where to look, not a point

    fake.FakeMap.all.length = 0
    mountMap({ region, centre: { lat: 45.0, lon: -122.0 } })
    expect(theMap().options).toMatchObject({ center: [-122.0, 45.0], zoom: 14 })

    fake.FakeMap.all.length = 0
    mountMap({ region, centre: { lat: 45.0, lon: -122.0 }, pin: LATLON })
    expect(theMap().options).toMatchObject({ center: [-122.6912, 45.52252], zoom: 17 })
  })

  it('sends every request with no referrer', () => {
    mountMap()
    const transform = theMap().options.transformRequest as (url: string) => unknown
    expect(transform('https://tiles.example.invalid/z/x/y.pbf')).toEqual({
      url: 'https://tiles.example.invalid/z/x/y.pbf',
      referrerPolicy: 'no-referrer',
    })
  })

  it('a tap sets the pin and a drag moves it', async () => {
    const wrapper = mountMap()
    const map = theMap()
    expect(fake.FakeMarker.all).toHaveLength(0)

    map.fire('click', { lngLat: { lng: -122.6912, lat: 45.52252 } })
    await flushPromises()
    expect((wrapper.props() as Record<string, unknown>).pin).toEqual(LATLON)
    expect(fake.FakeMarker.all).toHaveLength(1)
    const marker = fake.FakeMarker.all[0]
    expect(marker.options).toMatchObject({ draggable: true })
    expect(marker.lngLat).toEqual([-122.6912, 45.52252])

    marker.lngLat = [-122.69, 45.5226]
    marker.fire('dragend')
    await flushPromises()
    expect((wrapper.props() as Record<string, unknown>).pin).toEqual({ lat: 45.5226, lon: -122.69 })
    expect(fake.FakeMarker.all).toHaveLength(1) // the same marker moved
  })

  it('a click on the marker itself does not move the pin', async () => {
    const wrapper = mountMap({ pin: LATLON })
    const marker = fake.FakeMarker.all[0]
    const head = document.createElement('span') // the pin's drawing sits inside the marker's element
    marker.getElement().appendChild(head)

    theMap().fire('click', { lngLat: { lng: -122.69, lat: 45.5226 }, originalEvent: { target: head } })
    theMap().fire('click', { lngLat: { lng: -122.69, lat: 45.5226 }, originalEvent: { target: marker.getElement() } })
    await flushPromises()
    expect(wrapper.emitted('update:pin')).toBeUndefined()

    // a click on the map beside it still moves the pin
    theMap().fire('click', { lngLat: { lng: -122.69, lat: 45.5226 }, originalEvent: { target: document.body } })
    await flushPromises()
    expect(wrapper.emitted('update:pin')).toEqual([[{ lat: 45.5226, lon: -122.69 }]])
  })

  it('a longitude past 180 is wrapped', async () => {
    const wrapper = mountMap()
    theMap().fire('click', { lngLat: { lng: 237.3088, lat: 45.52252 } })
    await flushPromises()
    expect(((wrapper.props() as Record<string, unknown>).pin as { lon: number }).lon).toBeCloseTo(-122.6912, 6)

    theMap().fire('click', { lngLat: { lng: -482.6912, lat: 45.52252 } })
    await flushPromises()
    expect(((wrapper.props() as Record<string, unknown>).pin as { lon: number }).lon).toBeCloseTo(-122.6912, 6)
  })

  it('a double click or double tap does not zoom the map', () => {
    // Each tap of it would also place the pin, so zooming in that way would undo a careful drag
    mountMap()
    expect(theMap().options).toMatchObject({ doubleClickZoom: false })
  })

  it('rotation is off and the map is removed on unmount', () => {
    const wrapper = mountMap({ pin: LATLON })
    const map = theMap()
    expect(map.options).toMatchObject({ dragRotate: false, pitchWithRotate: false, maxPitch: 0, touchPitch: false })
    expect(map.touchZoomRotate.disableRotation).toHaveBeenCalled()
    expect(map.keyboard.disableRotation).toHaveBeenCalled() // the keyboard can't turn the map either
    expect(map.controls).toHaveLength(1)
    expect(map.controls[0].control).toBeInstanceOf(fake.FakeNavigationControl)
    expect((map.controls[0].control as { options: unknown }).options).toEqual({ showCompass: false })
    expect(map.options.attributionControl).toBeUndefined() // the library's own

    wrapper.unmount()
    expect(map.removed).toBe(true)
  })
})

describe('a map that cannot be made', () => {
  beforeEach(() => {
    document.body.replaceChildren()
    fake.FakeMap.all.length = 0
    fake.FakeMarker.all.length = 0
  })
  afterEach(() => {
    fake.FakeMap.failWith = null
    fake.FakeMap.failAfter = null
  })

  it('removes a map that was made before a later call threw, and says failed once', () => {
    fake.FakeMap.failAfter = new Error('a call after the constructor')
    const wrapper = mountMap({ pin: LATLON })
    expect(theMap().removed).toBe(true)
    expect(wrapper.emitted('failed')).toHaveLength(1)
    expect(wrapper.emitted('ready')).toBeUndefined()
    wrapper.unmount() // the map was dropped: unmounting removes nothing twice and is clean
  })

  it('says failed once when the browser has no WebGL2', () => {
    fake.FakeMap.failWith = new Error('Failed to initialize WebGL')
    const wrapper = mountMap({ pin: LATLON })
    expect(wrapper.emitted('failed')).toHaveLength(1)
    expect(wrapper.emitted('ready')).toBeUndefined()
    wrapper.unmount() // there is no map to remove: unmounting is clean
  })
})

describe('a map that never loads', () => {
  beforeEach(() => {
    document.body.replaceChildren()
    fake.FakeMap.all.length = 0
    vi.useFakeTimers()
  })
  afterEach(() => vi.useRealTimers())

  it('says ready once it loads, and never fails afterwards', () => {
    const wrapper = mountMap()
    theMap().fire('load')
    vi.advanceTimersByTime(60_000)
    theMap().fire('error', { error: new Error('a tile') })
    expect(wrapper.emitted('ready')).toHaveLength(1)
    expect(wrapper.emitted('failed')).toBeUndefined()
  })

  it('says failed once when nothing loads in 10 seconds', () => {
    const wrapper = mountMap()
    vi.advanceTimersByTime(9_999)
    expect(wrapper.emitted('failed')).toBeUndefined()
    vi.advanceTimersByTime(1)
    expect(wrapper.emitted('failed')).toHaveLength(1)
    vi.advanceTimersByTime(60_000)
    expect(wrapper.emitted('failed')).toHaveLength(1)
    expect(wrapper.emitted('ready')).toBeUndefined()
  })

  it('says failed once when an error comes before the load', () => {
    const wrapper = mountMap()
    theMap().fire('error', { error: new Error('no style') })
    theMap().fire('error', { error: new Error('no tiles') })
    expect(wrapper.emitted('failed')).toHaveLength(1)
    vi.advanceTimersByTime(60_000)
    expect(wrapper.emitted('failed')).toHaveLength(1)
  })
})
