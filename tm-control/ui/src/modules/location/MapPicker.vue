<!--
  The dialog that picks a point on a map: tap to place the pin, drag it to the exact spot, then Use this point. It
  answers with `picked` and closes; Cancel answers nothing. Use this point waits for the map itself to set the pin (a
  tap or a drag), so the field's own point is never written back as a pick, and stays off while the map has failed.
  The map is PinMap, loaded the first time the dialog opens, so MapLibre isn't part of the page's first download. The
  dialog says where the map comes from and that the device sends nothing: the phone's browser asks the map's host for
  the area it shows. When the map can't load (a phone with no internet, no WebGL, or a page left open across an
  upgrade, whose map file is gone), the dialog says so and offers Try again, which asks for the file again if it never
  came, and mounts the map afresh. It starts over each time it opens, at `start`, and is full-screen on a phone. The
  map stays mounted while the dialog fades out, so the body doesn't collapse, and is removed at after-leave.
-->
<script setup lang="ts">
import { computed, ref, shallowRef, watch, type Component } from 'vue'
import { useDisplay } from 'vuetify'
import { formatExact, type LatLon } from './coordinates'

const open = defineModel<boolean>('open', { required: true })
const props = defineProps<{
  styleUrl: string
  start: LatLon | null // the point already in the form's field, if any
  centre: LatLon | null // where to look first with no point: the place in use
  region: LatLon | null // where to look with neither: the device's time zone's city
}>()
const emit = defineEmits<{ picked: [point: LatLon] }>()

const { xs } = useDisplay()
const pin = ref<LatLon | null>(null)
const pinFromMap = ref(false) // whether the map itself set the pin: a tap or a drag, not the field's point
const failed = ref(false)
const attempt = ref(0) // a new key mounts the map afresh
// The map stays mounted while the dialog fades out, so its body doesn't collapse; after-leave removes it
const mapMounted = ref(false)

// PinMap, fetched on demand. Fetched by hand rather than with defineAsyncComponent, which keeps a failed load: a
// second try would reuse it and never ask again
const PinMap = shallowRef<Component>()

async function loadMap() {
  if (PinMap.value) return
  try {
    PinMap.value = (await import('./PinMap.vue')).default
  } catch {
    failed.value = true
  }
}

// Start over from the field's point each time the dialog opens
watch(
  open,
  (isOpen) => {
    if (!isOpen) return
    pin.value = props.start
    pinFromMap.value = false
    failed.value = false
    attempt.value += 1
    mapMounted.value = true
    void loadMap()
  },
  { immediate: true },
)

const host = computed(() => {
  try {
    return new URL(props.styleUrl).host
  } catch {
    return props.styleUrl
  }
})

function retry() {
  failed.value = false
  attempt.value += 1
  void loadMap()
}

// The map says where the pin is now
function pinned(point: LatLon | null) {
  pin.value = point
  pinFromMap.value = true
}

function use() {
  if (!pin.value || !pinFromMap.value || failed.value) return
  emit('picked', pin.value)
  open.value = false
}
</script>

<template>
  <v-dialog
    v-model="open"
    persistent
    max-width="720"
    :fullscreen="xs"
    scrollable
    aria-label="Pick the place on a map"
    @after-leave="mapMounted = false"
  >
    <v-card color="surface" :rounded="xs ? 0 : 'lg'" class="d-flex flex-column">
      <v-card-title class="text-h6 text-wrap pt-4">Pick the place on a map</v-card-title>
      <v-card-text class="d-flex flex-column flex-grow-1">
        <p class="text-body-2 text-secondary mb-4">
          The map comes from {{ host }}. Your phone asks it for the area you look at; this device sends it nothing.
        </p>
        <!-- In a block of its own: an alert's own flex settings would stretch or squash it in this column -->
        <div v-if="failed" class="mb-4">
          <v-alert type="warning">
            The map couldn't load. This phone may have no internet connection. Type or paste the coordinates instead.
            <div class="mt-3">
              <v-btn variant="outlined" min-height="44" @click="retry">Try again</v-btn>
            </div>
          </v-alert>
        </div>
        <div
          v-else-if="mapMounted"
          class="flex-grow-1 rounded border"
          :style="{ minHeight: '320px', height: xs ? undefined : '420px' }"
        >
          <component
            :is="PinMap"
            v-if="PinMap"
            :key="attempt"
            :pin="pin"
            :style-url="styleUrl"
            :centre="centre"
            :region="region"
            @update:pin="pinned"
            @failed="failed = true"
          />
        </div>
        <p v-if="pin || !failed" class="text-body-1 mt-4">
          <template v-if="pin">{{ formatExact(pin.lat, pin.lon) }}</template>
          <template v-else-if="!failed">Tap the map to place the pin, then drag it to the exact spot.</template>
        </p>
      </v-card-text>
      <v-card-actions class="px-4 pb-4">
        <v-spacer />
        <v-btn variant="text" min-height="44" @click="open = false">Cancel</v-btn>
        <v-btn color="primary" variant="flat" min-height="44" :disabled="!pin || !pinFromMap || failed" @click="use">Use this point</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
