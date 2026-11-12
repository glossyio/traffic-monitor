<!--
  The dialog for one camera's settings (PUT /cameras/{name}): whether to record its events, which radar it is paired
  with, and, when the Plate Recognizer add-on is installed, whether its events go there. The page does the saving: the
  dialog emits `save` with the values, and shows the `error` and `radarError` the page passes back. The form starts over
  from the row each time it opens; a camera being `adding` starts with record on, no radar, and no plates.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { radarChoices, type RadarOut, type Row } from './rows'

export interface CameraSettings {
  enabled: boolean
  camera_radar: string | null
  plate_recognizer: boolean | null
}

const open = defineModel<boolean>('open', { required: true })
const props = defineProps<{
  row: Row
  radars: RadarOut[]
  plates: boolean // the Plate Recognizer add-on is installed
  adding: boolean
  saving?: boolean
  error?: string // a failed save, from the page
  radarError?: string // the API refused the radar, from the page
}>()
const emit = defineEmits<{ save: [settings: CameraSettings]; cancel: [] }>()

// Vuetify's drop-down shows nothing for a null value, so "No radar" is the empty string in the field
const NO_RADAR = ''

const enabled = ref(true)
const radar = ref(NO_RADAR)
const sendPlates = ref(false)

watch(
  [open, () => props.row],
  ([isOpen]) => {
    if (!isOpen) return
    enabled.value = props.adding ? true : (props.row.enabled ?? true)
    radar.value = props.adding ? NO_RADAR : (props.row.camera_radar ?? NO_RADAR)
    sendPlates.value = props.adding ? false : (props.row.plate_recognizer ?? false)
  },
  { immediate: true },
)

const items = computed(() =>
  radarChoices(props.row, props.radars).map((choice) => ({ ...choice, value: choice.value ?? NO_RADAR })),
)

function save() {
  emit('save', {
    enabled: enabled.value,
    camera_radar: radar.value === NO_RADAR ? null : radar.value,
    plate_recognizer: props.plates ? sendPlates.value : null,
  })
}

function cancel() {
  emit('cancel')
  open.value = false
}

const title = computed(() =>
  props.adding ? `Add ${props.row.frigate_camera}` : `Settings for ${props.row.name ?? props.row.frigate_camera}`,
)
</script>

<template>
  <v-dialog v-model="open" max-width="520" :aria-label="title">
    <v-card color="surface" rounded="lg">
      <v-card-title class="text-h6 text-wrap pt-4">{{ title }}</v-card-title>
      <v-form @submit.prevent="save">
        <v-card-text>
          <v-switch v-model="enabled" label="Record events" color="primary" hide-details />
          <v-select
            v-model="radar"
            label="Radar"
            :items="items"
            item-props
            :error-messages="radarError ? [radarError] : []"
            variant="outlined"
            class="mt-4"
          />
          <v-switch
            v-if="plates"
            v-model="sendPlates"
            label="Send plates to Plate Recognizer"
            color="primary"
            hide-details
          />
          <v-alert v-if="error" type="error" class="mt-4">{{ error }}</v-alert>
        </v-card-text>
        <v-card-actions class="px-4 pb-4">
          <v-spacer />
          <v-btn variant="text" min-height="44" :disabled="saving" @click="cancel">Cancel</v-btn>
          <v-btn type="submit" color="primary" variant="flat" min-height="44" :loading="saving">{{
            adding ? 'Add' : 'Save'
          }}</v-btn>
        </v-card-actions>
      </v-form>
    </v-card>
  </v-dialog>
</template>
