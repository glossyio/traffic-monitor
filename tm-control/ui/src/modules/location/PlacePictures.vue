<!--
  A place's stored reference pictures, in its panel: newest first, each with both views at the column's width (never a
  thumbnail: this list is also where an administrator decides what to delete), the time, the camera, why it was taken,
  its mark's line, and the note for the first picture after a restart (plain text). Each has Download, which opens the
  review step (PictureReview) for that one picture, and Delete, which asks first. There is no button for several: a
  download is one picture. The place in use also offers Take a reference picture for each enabled camera
  (`cameras`, empty at any other place), which opens the Cameras page's dialog (ReferencePicture); a keep there, like a
  delete here, emits `changed`, so the page loads the list and the counts again.
  The page passes `pictures` (undefined until they are loaded) and `error` (why they couldn't be, with `retry`). The
  images are plain <img loading="lazy"> on the device's addresses, authorized by the session cookie; nothing is kept
  here. A delete that fails shows the API's message beside that row.
-->
<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import ReferencePicture from '../cameras/ReferencePicture.vue'
import PictureReview from './PictureReview.vue'
import { markLine, reasonWords, restartNote, storedUrl, type PictureOut } from './pictures'

type SurveyOut = components['schemas']['SurveyOut']

const EMPTY = 'No reference picture is stored for this place.'
const CLEAN_ALT = "The camera's view"
const ZONES_ALT = "The same view with Frigate's zone outlines"

const props = withDefaults(
  defineProps<{
    place: SurveyOut
    pictures: PictureOut[] | undefined // undefined until the page has loaded them
    cameras: string[] // the enabled cameras' keys when this is the place in use, else empty
    error?: string // why the list couldn't be loaded
  }>(),
  { error: '' },
)
const emit = defineEmits<{ changed: []; retry: [] }>()

// The API sends them newest first; the page doesn't rely on it
const newestFirst = computed(() =>
  [...(props.pictures ?? [])].sort((a, b) => Date.parse(b.taken_at) - Date.parse(a.taken_at)),
)

function when(picture: PictureOut) {
  return new Date(picture.taken_at).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

// Download: the review step for one picture. `reviewing` keeps the picture after the dialog closes, so it doesn't
// empty while it fades out.
const reviewOpen = ref(false)
const reviewing = ref<PictureOut | null>(null)
const hasLocation = computed(() => props.place.lat !== null && props.place.lon !== null)

function review(picture: PictureOut) {
  reviewing.value = picture
  reviewOpen.value = true
}

// Delete, after a confirmation. A failure shows beside the picture it was for.
const deleting = ref<PictureOut | null>(null)
const deleteOpen = computed({
  get: () => deleting.value !== null,
  set: (value: boolean) => {
    if (!value) deleting.value = null
  },
})
const working = ref<string | null>(null) // the id of the picture being deleted
const errors = reactive<Record<string, string>>({})

async function remove() {
  const picture = deleting.value
  if (!picture) return
  working.value = picture.id
  errors[picture.id] = ''
  try {
    await api.DELETE('/api/v1/pictures/{picture_id}', { params: { path: { picture_id: picture.id } } })
    emit('changed')
  } catch (failure) {
    errors[picture.id] = messageOf(failure)
  } finally {
    working.value = null
  }
}

// Take a reference picture: the Cameras page's dialog for one camera; `takes` counts the openings so each starts over
const takeOpen = ref(false)
const takeCamera = ref<string | null>(null)
const takes = ref(0)

function take(camera: string) {
  takeCamera.value = camera
  takes.value += 1
  takeOpen.value = true
}
</script>

<template>
  <div>
    <div v-if="cameras.length" class="d-flex flex-column ga-2 mb-4">
      <div v-for="camera in cameras" :key="camera" class="d-flex flex-wrap align-center gc-3">
        <span v-if="cameras.length > 1" class="text-body-1 font-weight-medium text-break">{{ camera }}</span>
        <v-btn
          variant="outlined"
          color="primary"
          min-height="44"
          :aria-label="cameras.length > 1 ? `Take a reference picture of ${camera}` : undefined"
          @click="take(camera)"
        >
          Take a reference picture
        </v-btn>
      </div>
    </div>

    <v-alert v-if="error" type="error" class="mb-4">
      {{ error }}
      <template #append>
        <v-btn variant="text" @click="emit('retry')">Try again</v-btn>
      </template>
    </v-alert>
    <v-progress-linear v-else-if="pictures === undefined" indeterminate color="primary" class="mb-4" />
    <p v-else-if="!pictures.length" class="text-body-1">{{ EMPTY }}</p>
    <ul v-else class="pictures d-flex flex-column ga-4">
      <li v-for="picture in newestFirst" :key="picture.id" class="border rounded pa-3" :data-picture="picture.id">
        <div class="d-flex flex-wrap align-baseline gc-3 mb-1">
          <span class="text-body-1 font-weight-medium">{{ when(picture) }}</span>
          <span class="text-body-2 text-secondary text-break">{{ picture.camera }}</span>
        </div>
        <div class="text-body-2" data-reason>{{ reasonWords(picture.reason) }}</div>
        <p v-if="restartNote(picture)" class="text-body-2 text-secondary mt-1" data-restart>
          {{ restartNote(picture) }}
        </p>
        <v-alert
          v-if="markLine(picture)"
          :type="markLine(picture)!.type"
          variant="tonal"
          class="mt-3 text-body-2"
          data-mark
        >
          {{ markLine(picture)!.text }}
        </v-alert>
        <div class="d-flex flex-column ga-3 my-3">
          <img
            :src="storedUrl(picture.id, 'clean.jpg')"
            :alt="CLEAN_ALT"
            loading="lazy"
            class="w-100 d-block rounded"
          />
          <img
            :src="storedUrl(picture.id, 'zones.jpg')"
            :alt="ZONES_ALT"
            loading="lazy"
            class="w-100 d-block rounded"
          />
        </div>
        <div class="d-flex flex-wrap ga-3">
          <v-btn variant="outlined" color="primary" min-height="44" @click="review(picture)">Download</v-btn>
          <v-btn
            variant="outlined"
            color="primary"
            min-height="44"
            :loading="working === picture.id"
            :disabled="working !== null"
            @click="deleting = picture"
          >
            Delete
          </v-btn>
        </div>
        <v-alert v-if="errors[picture.id]" type="error" class="mt-3">{{ errors[picture.id] }}</v-alert>
      </li>
    </ul>

    <PictureReview v-model:open="reviewOpen" :picture="reviewing" :has-location="hasLocation" />
    <ReferencePicture
      v-if="takeCamera"
      :key="takes"
      v-model:open="takeOpen"
      :name="takeCamera"
      @kept="emit('changed')"
    />
    <ConfirmDialog
      v-model="deleteOpen"
      title="Delete this picture?"
      text="Both views are removed from the device. This can't be undone."
      confirm-text="Delete"
      @confirm="remove"
    />
  </div>
</template>

<style scoped>
.pictures {
  list-style: none;
  padding: 0;
}
</style>
