<!--
  The button under a coordinates field that picks the point on a map (MapPicker), for the place form and the location
  correction. It shows nothing when the install has no map source. On the unit's own hotspot, which has no internet,
  it says so instead of offering a map that can't load. A picked point is written into the field as five decimal
  places, as the device keeps an exact location, and `picked` tells the form the map set it.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import type { components } from '../../api/schema'
import { useSession } from '../../stores/session'
import { formatExact, parsePair, type LatLon } from './coordinates'
import MapPicker from './MapPicker.vue'

type MapSources = components['schemas']['MapSources']

const props = defineProps<{ map: MapSources; centre: LatLon | null }>()
const coordinates = defineModel<string>('coordinates', { required: true })
const emit = defineEmits<{ picked: [] }>()

const session = useSession()
const onHotspot = computed(() => !!session.status?.hotspot)
const open = ref(false)

function picked(point: LatLon) {
  coordinates.value = formatExact(point.lat, point.lon)
  emit('picked')
}

// The picker starts at the point already in the field
const start = computed(() => parsePair(coordinates.value))
</script>

<template>
  <div v-if="map.style_url">
    <p v-if="onHotspot" class="text-body-2 text-secondary mt-4">
      The map needs the internet, and this device's hotspot has none. Type or paste the coordinates, or come back to
      this page once the device is on your Wi-Fi.
    </p>
    <template v-else>
      <v-btn variant="outlined" color="primary" min-height="44" @click="open = true">Pick on a map</v-btn>
      <MapPicker v-model:open="open" :style-url="map.style_url" :start="start" :centre="props.centre" @picked="picked" />
    </template>
  </div>
</template>
