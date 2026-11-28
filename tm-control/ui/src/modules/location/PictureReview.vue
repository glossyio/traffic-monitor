<!--
  The review step before a stored picture leaves the device (POST /pictures/{id}/package). It shows both views of that
  one picture at the full width of the dialog's column, so a person in view can be seen; above them the line for a
  `person` or `unchecked` mark (a warning or information, from `markLine`); under them, as plain text, the note for a
  picture taken after a restart (`restartNote`); then the box for the place's exact location, as the Cameras page's
  dialog has it, and the tick "I have looked at both views", without which Download stays off. A download is one
  picture, so the tick starts off for every picture and every opening, and it is off again once the zip is saved (the
  dialog closes then). The tick can't be set until both views have loaded (each image's `load`; the box says so in its
  hint), and a view that fails to load (`error`) says so in an alert above the views and keeps the box and Download
  off, because the tick is the only step between a stored picture and its leaving the device. The images are plain
  <img> on the device's addresses, loaded at once (the dialog holds exactly two); the session cookie authorizes them
  and the page keeps no copy. The zip is saved under the name in the answer's Content-Disposition. A 404 from the
  download means the picture is gone from the device: the dialog says so and asks for a reload. Any other refusal
  shows the API's message.
-->
<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ApiError, api, messageOf } from '../../api/client'
import { saveBlob } from '../../components/download'
import { markLine, restartNote, storedUrl, type PictureOut } from './pictures'

const TITLE = 'Look at both views before this picture leaves the device'
const INTRO =
  'This picture shows your street and whoever was in view. Anyone who has it can tell where the unit is. Look at both views before you download it.'
const GONE = 'This picture is no longer on the device. Reload the page.'
const WAITING = 'You can tick this once both views have loaded.'
const VIEW_FAILED = "A view didn't load. Close this and open it again."
const CLEAN_ALT = "The camera's view"
const ZONES_ALT = "The same view with Frigate's zone outlines"
const FALLBACK_NAME = 'reference-picture.zip'

const open = defineModel<boolean>('open', { required: true })
const props = defineProps<{
  picture: PictureOut | null
  hasLocation: boolean // whether the picture's place has a point the data file can hold
}>()

const looked = ref(false)
const withLocation = ref(true)
const saving = ref(false)
const error = ref('')
const gone = ref(false)
const loaded = reactive({ clean: false, zones: false }) // each view's `load`
const viewFailed = ref(false) // a view's `error`
const opened = ref(0) // changes with each reset, so the images are made again and load again

const mark = computed(() => (props.picture ? markLine(props.picture) : null))
const restart = computed(() => (props.picture ? restartNote(props.picture) : null))
const waiting = computed(() => !viewFailed.value && !(loaded.clean && loaded.zones))
const ready = computed(() => !viewFailed.value && loaded.clean && loaded.zones)

// Each opening, and each other picture, starts unticked and with the box as the place allows
watch(
  [open, () => props.picture?.id],
  () => {
    looked.value = false
    withLocation.value = props.hasLocation
    error.value = ''
    gone.value = false
    loaded.clean = false
    loaded.zones = false
    viewFailed.value = false
    opened.value += 1
  },
  { immediate: true },
)

// The file name in `attachment; filename="..."`
function fileName(header: string | null): string {
  const found = /filename="([^"]+)"/.exec(header ?? '')
  return found ? found[1] : FALLBACK_NAME
}

async function download() {
  const picture = props.picture
  if (!picture || !looked.value || !ready.value) return
  saving.value = true
  error.value = ''
  gone.value = false
  try {
    const { data, response } = await api.POST('/api/v1/pictures/{picture_id}/package', {
      params: { path: { picture_id: picture.id } },
      body: { location: withLocation.value && props.hasLocation, looked: true },
      parseAs: 'blob',
    })
    saveBlob(data as unknown as Blob, fileName(response.headers.get('Content-Disposition')))
    open.value = false
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 404) gone.value = true
    else error.value = messageOf(failure)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <v-dialog v-model="open" max-width="720" scrollable :aria-label="TITLE">
    <v-card v-if="picture" color="surface" rounded="lg">
      <v-card-title class="text-h6 text-wrap pt-4">{{ TITLE }}</v-card-title>
      <v-card-text>
        <p class="text-body-1 mb-4">{{ INTRO }}</p>
        <v-alert v-if="mark" :type="mark.type" variant="tonal" class="mb-4 text-body-2" data-mark>
          {{ mark.text }}
        </v-alert>
        <v-alert v-if="gone" type="info" variant="tonal" class="mb-4" data-gone>{{ GONE }}</v-alert>
        <v-alert v-if="error" type="error" class="mb-4">{{ error }}</v-alert>
        <v-alert v-if="viewFailed" type="error" class="mb-4" data-view-failed>{{ VIEW_FAILED }}</v-alert>

        <img
          :key="`clean-${opened}`"
          :src="storedUrl(picture.id, 'clean.jpg')"
          :alt="CLEAN_ALT"
          class="w-100 d-block rounded"
          @load="loaded.clean = true"
          @error="viewFailed = true"
        />
        <p class="text-body-2 mt-1 mb-4">{{ CLEAN_ALT }}</p>
        <img
          :key="`zones-${opened}`"
          :src="storedUrl(picture.id, 'zones.jpg')"
          :alt="ZONES_ALT"
          class="w-100 d-block rounded"
          @load="loaded.zones = true"
          @error="viewFailed = true"
        />
        <p class="text-body-2 mt-1 mb-4">{{ ZONES_ALT }}</p>
        <p v-if="restart" class="text-body-2 mb-4" data-restart>{{ restart }}</p>

        <v-checkbox
          v-model="withLocation"
          label="Include this place's exact location"
          :disabled="!hasLocation"
          :hint="hasLocation ? '' : 'This place has no coordinates, so the data file holds no location.'"
          :persistent-hint="!hasLocation"
          :hide-details="hasLocation"
          color="primary"
        />
        <v-checkbox
          v-model="looked"
          label="I have looked at both views"
          :disabled="!ready"
          :hint="waiting ? WAITING : ''"
          :persistent-hint="waiting"
          :hide-details="!waiting"
          color="primary"
          class="mt-2"
        />
      </v-card-text>
      <v-card-actions class="flex-wrap px-4 pb-4">
        <v-spacer />
        <v-btn variant="text" min-height="44" @click="open = false">Close</v-btn>
        <v-btn
          color="primary"
          variant="flat"
          min-height="44"
          :loading="saving"
          :disabled="!looked || !ready"
          @click="download"
        >
          Download
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
