<!--
  The dialog that adds a place (POST /surveys) or, given a planned `survey`, edits it (PATCH /surveys/{id}): a private
  description, the coordinates as one "latitude, longitude" field, and a bearing for each enabled sensor. On a secure
  (HTTPS) page the phone can fill in the coordinates; on plain HTTP browsers don't share a location, and the form says
  so. The form starts over each time it opens. Emits `saved` with the place the API answered, then closes.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import { BEARINGS, formatExact, parsePair, startingBearings } from './coordinates'

type Bearing = components['schemas']['Bearing']
type SurveyOut = components['schemas']['SurveyOut']

const open = defineModel<boolean>('open', { required: true })
const props = defineProps<{
  sensors: Bearing[] // the enabled sensors, each with its bearing in config.yml now
  survey?: SurveyOut // the planned place to edit; none to add one
}>()
const emit = defineEmits<{ saved: [survey: SurveyOut] }>()

const description = ref('')
const coordinates = ref('')
const bearings = ref<Bearing[]>([])
const saving = ref(false)
const error = ref('')
const locating = ref(false)
const locateError = ref('')

// Start over from the place being edited, or from blank, each time the dialog opens
watch(
  open,
  (isOpen) => {
    if (!isOpen) return
    const survey = props.survey
    description.value = survey?.description ?? ''
    coordinates.value = survey && survey.lat !== null ? formatExact(survey.lat, survey.lon) : ''
    bearings.value = startingBearings(props.sensors, survey)
    error.value = ''
    locateError.value = ''
  },
  { immediate: true },
)

// The pair typed or pasted. A blank field is a place with no location; text that isn't a pair can't be saved.
const pair = computed(() => parsePair(coordinates.value))
const coordinatesError = computed(() =>
  coordinates.value.trim() && !pair.value ? 'Enter latitude, longitude with a dot as the decimal mark' : '',
)

// The phone's location. Browsers share it only with secure pages, and the device is usually reached over plain HTTP.
const secure = window.isSecureContext

function useThisPhone() {
  locateError.value = ''
  if (!navigator.geolocation) {
    locateError.value = "This browser doesn't share its location. Paste coordinates instead."
    return
  }
  locating.value = true
  navigator.geolocation.getCurrentPosition(
    (position) => {
      locating.value = false
      // Five decimal places, as the device keeps them (about a metre)
      coordinates.value = `${position.coords.latitude.toFixed(5)}, ${position.coords.longitude.toFixed(5)}`
    },
    (refused) => {
      locating.value = false
      locateError.value = `The browser didn't share this phone's location (${refused.message || 'no reason given'}).`
    },
    { enableHighAccuracy: true, timeout: 30000, maximumAge: 0 },
  )
}

async function save() {
  if (coordinatesError.value) return
  saving.value = true
  error.value = ''
  const body = {
    description: description.value.trim() || null,
    lat: pair.value?.lat ?? null,
    lon: pair.value?.lon ?? null,
    bearings: bearings.value,
  }
  try {
    const { data } = props.survey
      ? await api.PATCH('/api/v1/surveys/{survey_id}', { params: { path: { survey_id: props.survey.id } }, body })
      : await api.POST('/api/v1/surveys', { body })
    emit('saved', data as SurveyOut)
    open.value = false
  } catch (failure) {
    error.value = messageOf(failure)
  } finally {
    saving.value = false
  }
}

const title = computed(() => {
  if (!props.survey) return 'Add a place'
  return props.survey.description ? `Edit "${props.survey.description}"` : `Edit place ${props.survey.id}`
})
</script>

<template>
  <v-dialog v-model="open" max-width="560">
    <v-card color="surface" rounded="lg">
      <v-card-title class="text-h6 text-wrap pt-4">{{ title }}</v-card-title>
      <v-form @submit.prevent="save">
        <v-card-text>
          <v-text-field
            v-model="description"
            label="Description"
            hint="Private: it never leaves the device"
            persistent-hint
            maxlength="200"
            variant="outlined"
            class="mb-4"
          />
          <v-text-field
            v-model="coordinates"
            label="Coordinates"
            hint="Paste latitude, longitude from a maps app, such as 45.52252, -122.69120"
            persistent-hint
            :error-messages="coordinatesError"
            inputmode="decimal"
            autocomplete="off"
            spellcheck="false"
            variant="outlined"
            class="mb-2"
          />
          <v-btn
            v-if="secure"
            variant="outlined"
            color="primary"
            min-height="44"
            :loading="locating"
            @click="useThisPhone"
          >
            Use this phone's location
          </v-btn>
          <p v-else class="text-body-2 text-secondary">
            Browsers only share your location with secure pages. Paste coordinates instead.
          </p>
          <v-alert v-if="locateError" type="warning" class="mt-4">{{ locateError }}</v-alert>
          <p class="text-body-2 text-secondary mt-2">A map pin is coming in a later update.</p>

          <template v-if="bearings.length">
            <h3 class="text-subtitle-1 font-weight-medium mt-6">Which way each sensor faces here</h3>
            <v-select
              v-for="bearing in bearings"
              :key="`${bearing.sensor_type}/${bearing.sensor_name}`"
              v-model="bearing.bearing"
              :label="`Bearing, ${bearing.sensor_name}`"
              :items="BEARINGS"
              variant="outlined"
              hide-details
              class="mt-4"
            />
          </template>

          <v-alert v-if="error" type="error" class="mt-4">{{ error }}</v-alert>
        </v-card-text>
        <v-card-actions class="px-4 pb-4">
          <v-spacer />
          <v-btn variant="text" min-height="44" :disabled="saving" @click="open = false">Cancel</v-btn>
          <v-btn
            type="submit"
            color="primary"
            variant="flat"
            min-height="44"
            :loading="saving"
            :disabled="!!coordinatesError"
          >
            Save
          </v-btn>
        </v-card-actions>
      </v-form>
    </v-card>
  </v-dialog>
</template>
