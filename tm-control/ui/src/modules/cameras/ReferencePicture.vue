<!--
  The reference picture of one camera (its sensors.cameras key, `name`), for a tool that places recorded paths on a
  street. Two steps: first the intro and the note on what the picture gives away, before any picture is taken; then,
  after Take the pictures (POST /cameras/{name}/reference), both pictures as the device holds them, the people line,
  the zones' legend, the location box, and Save the zip.
  The pictures are plain <img> elements: the session cookie authorizes them, and the page keeps nothing once the
  dialog closes. Closing the dialog, or taking again, drops the pictures the device holds (DELETE, answer ignored). The
  dialog starts over each time it opens. A 404 from Save, or a picture that fails to load, means the device no longer
  holds them: the dialog goes back to its first step and says so. Any other refusal shows the API's message.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ApiError, api, messageOf } from '../../api/client'
import { saveBlob } from '../../components/download'
import { legendRows, peopleLine, pictureUrl, type ReferenceOut } from './reference'

const INTRO =
  'A still picture of what this camera sees, and the same view with its zones marked, for a tool that places ' +
  'recorded paths on a street. You get one zip with both pictures, a data file with the zones, and a labelled drawing.'
const NOTE =
  'This picture shows your street. Anyone who has it can tell where the unit is, and it shows whoever was in view. ' +
  'Take it when nobody is in the picture, look at both pictures before you save them, and share them only with ' +
  "people you would give the unit's exact location. The data file also holds that location unless you clear the " +
  'box below.'
const EXPIRED = 'These pictures are no longer held on the device. Take them again.'
const CLEAN_ALT = "The camera's view"
const ZONES_ALT = "The same view with Frigate's zone outlines"

const open = defineModel<boolean>('open', { required: true })
const props = defineProps<{ name: string }>()

const reference = ref<ReferenceOut | null>(null)
const withLocation = ref(true)
const taking = ref(false)
const saving = ref(false)
const error = ref('')
const expired = ref(false)

const title = computed(() => `Reference picture of ${props.name}`)
const people = computed(() => (reference.value ? peopleLine(reference.value.people) : null))
const legend = computed(() => (reference.value ? legendRows(reference.value) : []))

// Tell the device to forget the pictures it holds for this dialog; its answer doesn't matter
function drop() {
  const held = reference.value
  reference.value = null
  if (!held) return
  void api
    .DELETE('/api/v1/cameras/{name}/reference/{ticket}', { params: { path: { name: props.name, ticket: held.ticket } } })
    .catch(() => {})
}

// Each opening starts at the first step; closing drops what the device holds
watch(
  open,
  (isOpen) => {
    if (isOpen) {
      reference.value = null
      error.value = ''
      expired.value = false
    } else {
      drop()
    }
  },
  { immediate: true },
)

// Back to the first step, saying the pictures are gone
function gone() {
  reference.value = null
  error.value = ''
  expired.value = true
}

async function take() {
  drop()
  taking.value = true
  error.value = ''
  expired.value = false
  try {
    const { data } = await api.POST('/api/v1/cameras/{name}/reference', { params: { path: { name: props.name } } })
    reference.value = data as ReferenceOut
    withLocation.value = reference.value.has_location
  } catch (failure) {
    error.value = messageOf(failure)
  } finally {
    taking.value = false
  }
}

async function save() {
  const held = reference.value
  if (!held) return
  saving.value = true
  error.value = ''
  try {
    const { data } = await api.GET('/api/v1/cameras/{name}/reference/{ticket}/package', {
      params: { path: { name: props.name, ticket: held.ticket }, query: { location: withLocation.value } },
      parseAs: 'blob',
    })
    saveBlob(data as Blob, `${held.stem}.zip`)
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 404) gone()
    else error.value = messageOf(failure)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <v-dialog v-model="open" max-width="1080" scrollable :aria-label="title">
    <v-card color="surface" rounded="lg">
      <v-card-title class="text-h6 text-wrap pt-4">{{ title }}</v-card-title>
      <v-card-text>
        <p class="text-body-1 mb-4">{{ INTRO }}</p>
        <v-alert type="warning" variant="tonal" class="mb-4 text-body-2" data-note>{{ NOTE }}</v-alert>
        <v-alert v-if="expired" type="info" variant="tonal" class="mb-4" data-expired>{{ EXPIRED }}</v-alert>
        <v-alert v-if="error" type="error" class="mb-4">{{ error }}</v-alert>

        <template v-if="reference && people">
          <div class="mb-4" data-people>
            <v-alert v-if="people.type" :type="people.type" class="text-body-2">{{ people.text }}</v-alert>
            <p v-else class="text-body-2">{{ people.text }}</p>
          </div>

          <v-row dense>
            <v-col cols="12" md="6">
              <img
                :src="pictureUrl(name, reference.ticket, 'clean.jpg')"
                :alt="CLEAN_ALT"
                class="w-100 d-block rounded"
                @error="gone"
              />
              <p class="text-body-2 mt-1">{{ CLEAN_ALT }}</p>
            </v-col>
            <v-col cols="12" md="6">
              <img
                :src="pictureUrl(name, reference.ticket, 'zones.jpg')"
                :alt="ZONES_ALT"
                class="w-100 d-block rounded"
                @error="gone"
              />
              <p class="text-body-2 mt-1">{{ ZONES_ALT }}</p>
            </v-col>
          </v-row>
          <p class="text-body-2 text-secondary mt-2">The two were taken a moment apart.</p>
          <p class="text-body-2 text-secondary mb-4">
            The device holds these pictures in memory for 10 minutes and never saves them.
          </p>

          <h2 class="text-subtitle-1 font-weight-bold mb-2">Zones</h2>
          <div v-for="row in legend" :key="row.key" class="d-flex align-start ga-2 text-body-2 mb-2" data-legend-row>
            <v-sheet :color="row.color" width="16" height="16" rounded="sm" class="flex-shrink-0 mt-1" />
            <div class="text-break">
              <span class="font-weight-bold">{{ row.key }}</span>
              <span v-if="row.detail" class="text-secondary ms-2">{{ row.detail }}</span>
            </div>
          </div>

          <v-checkbox
            v-model="withLocation"
            label="Include this place's exact location"
            :disabled="!reference.has_location"
            :hint="
              reference.has_location ? '' : 'No place with coordinates is in use, so the data file holds no location.'
            "
            :persistent-hint="!reference.has_location"
            color="primary"
            class="mt-2"
          />
        </template>
      </v-card-text>
      <v-card-actions class="flex-wrap px-4 pb-4">
        <v-spacer />
        <v-btn variant="text" min-height="44" @click="open = false">Close</v-btn>
        <template v-if="reference">
          <v-btn variant="text" color="primary" min-height="44" :loading="taking" :disabled="saving" @click="take">
            Take again
          </v-btn>
          <v-btn color="primary" variant="flat" min-height="44" :loading="saving" :disabled="taking" @click="save">
            Save the zip
          </v-btn>
        </template>
        <v-btn v-else color="primary" variant="flat" min-height="44" :loading="taking" @click="take">
          Take the pictures
        </v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
