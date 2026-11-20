<!--
  The map the picker shows, and the only code that imports MapLibre. MapPicker loads this file on demand, so the library
  and its worker stay out of the page's first download. The phone's browser fetches the map's style, tiles, fonts, and
  sprites from `styleUrl`'s host; the device fetches nothing, and every request is sent with no referrer.
  It opens at the pin (zoom 17), else at `centre` (zoom 14), else on the whole world. A tap sets `pin`, and the marker
  can be dragged to the exact spot. Rotation and tilt are off, so north stays up. It says `ready` when the map has
  loaded and `failed`, once, when the browser can't make the map (no WebGL2), an error comes first, or nothing has
  loaded in 10 seconds (no internet, say). A longitude is wrapped into -180 to 180, because the map repeats the world
  sideways; nothing here rounds a value.
-->
<script setup lang="ts">
import { Map as MapLibreMap, Marker, NavigationControl, setWorkerUrl } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useTheme } from 'vuetify'
import type { LatLon } from './coordinates'

// How long the map has to load before the picker gives up on it
const LOAD_TIMEOUT_MS = 10000

const props = defineProps<{ styleUrl: string; centre: LatLon | null }>()
const pin = defineModel<LatLon | null>('pin', { required: true })
const emit = defineEmits<{ ready: []; failed: [] }>()

const element = ref<HTMLElement | null>(null)
const theme = useTheme()

let map: MapLibreMap | null = null
let marker: Marker | null = null
let timer: ReturnType<typeof setTimeout> | undefined
let loaded = false
let failedOnce = false

function wrapLongitude(lon: number): number {
  return lon > 180 || lon < -180 ? ((((lon + 180) % 360) + 360) % 360) - 180 : lon
}

function setPin(lat: number, lon: number) {
  pin.value = { lat, lon: wrapLongitude(lon) }
}

function fail() {
  if (loaded || failedOnce) return
  failedOnce = true
  clearTimeout(timer)
  emit('failed')
}

// Keep the marker where the pin is, making it the first time there is one
function placeMarker(value: LatLon | null) {
  if (!map) return
  if (!value) {
    marker?.remove()
    marker = null
    return
  }
  if (!marker) {
    marker = new Marker({ draggable: true, color: theme.current.value.colors.primary })
    marker.on('dragend', () => {
      const dropped = marker!.getLngLat()
      setPin(dropped.lat, dropped.lng)
    })
    marker.setLngLat([value.lon, value.lat]).addTo(map)
  } else {
    marker.setLngLat([value.lon, value.lat])
  }
}

onMounted(() => {
  try {
    setWorkerUrl(workerUrl)
    const start = pin.value ?? props.centre
    map = new MapLibreMap({
      container: element.value!,
      style: props.styleUrl,
      center: start ? [start.lon, start.lat] : [0, 20],
      zoom: pin.value ? 17 : props.centre ? 14 : 1,
      // North stays up and the map stays flat: nothing here needs a bearing or a tilt
      dragRotate: false,
      pitchWithRotate: false,
      maxPitch: 0,
      touchPitch: false,
      // A double click or double tap would zoom in, but each tap of it also places the pin; pinch, the wheel, and the
      // buttons still zoom
      doubleClickZoom: false,
      // No referrer on any request: the map's host learns the area, not which page asked
      transformRequest: (url) => ({ url, referrerPolicy: 'no-referrer' }),
    })
    map.touchZoomRotate.disableRotation()
    map.keyboard.disableRotation()
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    map.on('load', () => {
      loaded = true
      clearTimeout(timer)
      emit('ready')
    })
    map.on('error', fail)
    map.on('click', (event) => {
      // The marker sits on the map, so a tap on it reaches here too, and would move the pin a little
      const target = event.originalEvent?.target
      if (target instanceof Node && marker?.getElement().contains(target)) return
      setPin(event.lngLat.lat, event.lngLat.lng)
    })
    timer = setTimeout(fail, LOAD_TIMEOUT_MS)
    placeMarker(pin.value)
  } catch {
    // The browser can't make the map (no WebGL2, say): the picker says so, like any other failure
    map = null
    fail()
  }
})

watch(pin, placeMarker)

onBeforeUnmount(() => {
  clearTimeout(timer)
  marker?.remove()
  map?.remove()
  marker = null
  map = null
})
</script>

<template>
  <div ref="element" class="w-100 h-100" />
</template>
