<!--
  The dialog that corrects a value entered wrong at a used place or the place in use. It never moves the unit: Deploy
  here does that, and the dialog says so.
  - kind 'location': the place's point (POST /surveys/{id}/location). A new point more than about 1 km from the old one
    looks more like a move than a typo, so Correct asks a second time before it sends. A correction needs a point: a
    place with none isn't offered one, and the field can't be left blank.
  - kind 'bearing': which way the sensor faced in one of the place's deployments
    (POST /surveys/{id}/deployments/{deployment_id}/bearing).
  The dialog starts over each time it opens. Emits `corrected` once the API has answered, then closes; and `stale`
  when the API refused because config.yml or the place changed since the page loaded (409), or Node-RED failed after
  the place was changed (502), so the page loads the places again.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ApiError, api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { BEARINGS, distanceKm, formatExact, parsePair } from './coordinates'

type SurveyOut = components['schemas']['SurveyOut']
type DeploymentOut = components['schemas']['DeploymentOut']

// A new point farther than this from the old one looks like a move, not a typo
const FAR_KM = 1

const open = defineModel<boolean>('open', { required: true })
const props = defineProps<{
  kind: 'location' | 'bearing'
  place: SurveyOut // a used place or the place in use; with a point, for a location correction
  deployment?: DeploymentOut // the deployment whose bearing to correct
}>()
const emit = defineEmits<{ corrected: []; stale: [] }>()

const coordinates = ref('')
const bearing = ref('')
const reason = ref('')
const saving = ref(false)
const error = ref('')
const confirmFar = ref(false)

// Start over from the place's point or the deployment's bearing each time the dialog opens
watch(
  open,
  (isOpen) => {
    if (!isOpen) return
    coordinates.value = props.place.lat !== null ? formatExact(props.place.lat, props.place.lon) : ''
    bearing.value = props.deployment?.bearing ?? ''
    reason.value = ''
    error.value = ''
  },
  { immediate: true },
)

const title = computed(() => (props.kind === 'location' ? 'Correct location' : 'Correct bearing'))

// The pair typed or pasted, checked as in the place form
const pair = computed(() => parsePair(coordinates.value))
const coordinatesError = computed(() =>
  coordinates.value.trim() && !pair.value ? 'Enter latitude, longitude with a dot as the decimal mark' : '',
)

// How far the new point is from the old one, in km
const distance = computed(() => {
  const { lat, lon } = props.place
  if (!pair.value || lat === null || lon === null) return 0
  return distanceKm({ lat, lon }, pair.value)
})

// The same point again is allowed: after a 502, correcting again with it finishes the job. The same bearing isn't,
// because nothing has changed by the time that request fails.
const canCorrect = computed(() =>
  props.kind === 'location' ? pair.value !== null : bearing.value !== (props.deployment?.bearing ?? ''),
)

// The second confirmation's text, with the distance in whole km
const farText = computed(
  () =>
    `The new point is about ${Math.round(distance.value)} km from the old one. ` +
    'If the unit moved, deploy it to the place it moved to instead.',
)

function askToCorrect() {
  if (!canCorrect.value) return
  if (props.kind === 'location' && distance.value > FAR_KM) confirmFar.value = true
  else void correct()
}

async function correct() {
  saving.value = true
  error.value = ''
  const why = reason.value.trim() || null
  try {
    if (props.kind === 'location' && pair.value) {
      await api.POST('/api/v1/surveys/{survey_id}/location', {
        params: { path: { survey_id: props.place.id } },
        body: { lat: pair.value.lat, lon: pair.value.lon, reason: why },
      })
    } else if (props.kind === 'bearing' && props.deployment) {
      await api.POST('/api/v1/surveys/{survey_id}/deployments/{deployment_id}/bearing', {
        params: { path: { survey_id: props.place.id, deployment_id: props.deployment.id } },
        body: { bearing: bearing.value, reason: why },
      })
    }
    emit('corrected')
    open.value = false
  } catch (failure) {
    error.value = messageOf(failure)
    if (failure instanceof ApiError && (failure.status === 409 || failure.status === 502)) emit('stale')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <v-dialog v-model="open" max-width="560" :aria-label="title">
    <v-card color="surface" rounded="lg">
      <v-card-title class="text-h6 text-wrap pt-4">{{ title }}</v-card-title>
      <v-form @submit.prevent="askToCorrect">
        <v-card-text>
          <p class="text-subtitle-1 font-weight-medium text-break">{{ place.description ?? 'No description' }}</p>
          <p class="text-body-2 text-secondary mb-4">{{ place.id }}</p>

          <template v-if="kind === 'location'">
            <p class="text-body-1 mb-6">
              Use this only if the location was entered wrong. Every record from this place will say it was at the new
              point. If the unit moved, deploy it to the place it moved to instead.
            </p>
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
              :disabled="saving"
              class="mb-4"
            />
          </template>

          <template v-else-if="deployment">
            <p class="text-body-1 font-weight-medium text-break">{{ deployment.sensor_name }}</p>
            <p class="text-body-2 text-secondary text-break mb-4">{{ deployment.id }}</p>
            <p class="text-body-1 mb-6">
              Use this only if the bearing was entered wrong. Every record from this deployment will say the sensor
              faced the new way. If the unit was turned, use Modify deployment on the place in use instead.
            </p>
            <v-select
              v-model="bearing"
              label="Bearing"
              :items="BEARINGS"
              variant="outlined"
              :disabled="saving"
              hide-details
              class="mb-6"
            />
          </template>

          <v-text-field
            v-model="reason"
            label="Reason"
            hint="Optional. Kept with the correction on this device."
            persistent-hint
            maxlength="200"
            variant="outlined"
            :disabled="saving"
          />
          <p class="text-body-2 text-secondary mt-4">
            Copies and uploads that already left the device keep the old values.
          </p>
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
            :disabled="!canCorrect"
          >
            Correct
          </v-btn>
        </v-card-actions>
      </v-form>
    </v-card>
  </v-dialog>
  <ConfirmDialog
    v-model="confirmFar"
    title="That's far enough to look like a move. Correct it anyway?"
    :text="farText"
    confirm-text="Correct it anyway"
    @confirm="correct"
  />
</template>
