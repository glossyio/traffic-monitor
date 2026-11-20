<!--
  The dialog that picks a point on a map: tap to place the pin, drag it to the exact spot, then Use this point. It
  answers with `picked` and closes; Cancel answers nothing. The map is PinMap, loaded the first time the dialog opens,
  so MapLibre isn't part of the page's first download. The dialog says where the map comes from and that the device
  sends nothing: the phone's browser asks the map's host for the area it shows. When the map can't load (a phone with
  no internet), the dialog says so and offers Try again, which mounts the map afresh. It starts over each time it
  opens, at `start`, and is full-screen on a phone.
-->
<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import { useDisplay } from 'vuetify'
import { formatExact, type LatLon } from './coordinates'

const PinMap = defineAsyncComponent(() => import('./PinMap.vue'))

const open = defineModel<boolean>('open', { required: true })
const props = defineProps<{
  styleUrl: string
  start: LatLon | null // the point already in the form's field, if any
  centre: LatLon | null // where to look first with no point: the place in use
}>()
const emit = defineEmits<{ picked: [point: LatLon] }>()

const { xs } = useDisplay()
const pin = ref<LatLon | null>(null)
const failed = ref(false)
const attempt = ref(0) // a new key mounts the map afresh

// Start over from the field's point each time the dialog opens
watch(
  open,
  (isOpen) => {
    if (!isOpen) return
    pin.value = props.start
    failed.value = false
    attempt.value += 1
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
}

function use() {
  if (!pin.value) return
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
  >
    <v-card color="surface" :rounded="xs ? 0 : 'lg'" class="d-flex flex-column">
      <v-card-title class="text-h6 text-wrap pt-4">Pick the place on a map</v-card-title>
      <v-card-text class="d-flex flex-column flex-grow-1">
        <p class="text-body-2 text-secondary mb-4">
          The map comes from {{ host }}. Your phone asks it for the area you look at; this device sends it nothing.
        </p>
        <v-alert v-if="failed" type="warning" class="mb-4">
          The map couldn't load. This phone may have no internet connection. Type or paste the coordinates instead.
          <div class="mt-3">
            <v-btn variant="outlined" min-height="44" @click="retry">Try again</v-btn>
          </div>
        </v-alert>
        <div
          v-else-if="open"
          class="flex-grow-1 rounded border"
          :style="{ minHeight: '320px', height: xs ? undefined : '420px' }"
        >
          <PinMap :key="attempt" v-model:pin="pin" :style-url="styleUrl" :centre="centre" @failed="failed = true" />
        </div>
        <p class="text-body-1 mt-4">
          <template v-if="pin">{{ formatExact(pin.lat, pin.lon) }}</template>
          <template v-else>Tap the map to place the pin, then drag it to the exact spot.</template>
        </p>
      </v-card-text>
      <v-card-actions class="px-4 pb-4">
        <v-spacer />
        <v-btn variant="text" min-height="44" @click="open = false">Cancel</v-btn>
        <v-btn color="primary" variant="flat" min-height="44" :disabled="!pin" @click="use">Use this point</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
