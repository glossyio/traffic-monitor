<!--
  The dialog that corrects a value entered wrong at a used place or the place in use. It never moves the unit: Deploy
  here does that, and the dialog says so.
  - kind 'location': the place's point (POST /surveys/{id}/location). A new point more than about 1 km from the old one
    looks more like a move than a typo, so Correct asks a second time before it sends. A correction needs a point: a
    place with none isn't offered one, and the field can't be left blank.
  - kind 'heading': which way the sensor faced in one of the place's deployments, in degrees
    (POST /surveys/{id}/deployments/{deployment_id}/heading).
  A map button under the coordinates picks the point on a map, and a line warns when fewer than four decimal places
  are typed; a point picked far away asks the second question like a typed one. The dialog starts over each time it
  opens. Emits `corrected` (with whether the map set the point last) once the API has answered, then closes; and `stale`
  when the API refused because config.yml or the place changed since the page loaded (409), or Node-RED failed after
  the place was changed (502), so the page loads the places again.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ApiError, api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { distanceKm, fewDecimalsWarning, formatExact, parsePair, type LatLon } from './coordinates'
import HeadingPick from './HeadingPick.vue'
import MapPickButton from './MapPickButton.vue'

type SurveyOut = components['schemas']['SurveyOut']
type DeploymentOut = components['schemas']['DeploymentOut']
type MapSources = components['schemas']['MapSources']

// A new point farther than this from the old one looks like a move, not a typo
const FAR_KM = 1

const open = defineModel<boolean>('open', { required: true })
const props = defineProps<{
  kind: 'location' | 'heading'
  place: SurveyOut // a used place or the place in use; with a point, for a location correction
  deployment?: DeploymentOut // the deployment whose heading to correct
  map: MapSources // where the map comes from; null style_url is no map
  centre: LatLon | null // where the map looks first with no point: the place in use
}>()
const emit = defineEmits<{ corrected: [onMap: boolean]; stale: [] }>()

const coordinates = ref('')
const onMap = ref(false) // whether the map set the coordinates last
const heading = ref<number | null>(null)
const reason = ref('')
const saving = ref(false)
const error = ref('')
const confirmFar = ref(false)

// Start over from the place's point or the deployment's heading each time the dialog opens
watch(
  open,
  (isOpen) => {
    if (!isOpen) return
    coordinates.value = props.place.lat !== null ? formatExact(props.place.lat, props.place.lon) : ''
    heading.value = props.deployment?.heading_deg ?? null
    reason.value = ''
    onMap.value = false
    error.value = ''
  },
  { immediate: true },
)

const title = computed(() => (props.kind === 'location' ? 'Correct location' : 'Correct heading'))

// The pair typed or pasted, checked as in the place form
const pair = computed(() => parsePair(coordinates.value))
const coordinatesError = computed(() =>
  coordinates.value.trim() && !pair.value ? 'Enter latitude, longitude with a dot as the decimal mark' : '',
)
const fewDecimals = computed(() => fewDecimalsWarning(coordinates.value))

// How far the new point is from the old one, in km
const distance = computed(() => {
  const { lat, lon } = props.place
  if (!pair.value || lat === null || lon === null) return 0
  return distanceKm({ lat, lon }, pair.value)
})

// The same point again is allowed: after a 502, correcting again with it finishes the job. The same heading isn't,
// because nothing has changed by the time that request fails.
const canCorrect = computed(() =>
  props.kind === 'location' ? pair.value !== null : heading.value !== (props.deployment?.heading_deg ?? null),
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
    } else if (props.kind === 'heading' && props.deployment) {
      await api.POST('/api/v1/surveys/{survey_id}/deployments/{deployment_id}/heading', {
        params: { path: { survey_id: props.place.id, deployment_id: props.deployment.id } },
        body: { heading_deg: heading.value, reason: why },
      })
    }
    emit('corrected', onMap.value)
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
              :class="map.style_url ? 'mb-2' : 'mb-4'"
              @update:model-value="onMap = false"
            />
            <p v-if="fewDecimals" class="text-body-2 text-warning mt-3 mb-2">{{ fewDecimals }}</p>
            <MapPickButton
              v-model:coordinates="coordinates"
              :map="map"
              :centre="centre"
              class="mb-4"
              @picked="onMap = true"
            />
          </template>

          <template v-else-if="deployment">
            <p class="text-body-1 font-weight-medium text-break">{{ deployment.sensor_name }}</p>
            <p class="text-body-2 text-secondary text-break mb-4">{{ deployment.id }}</p>
            <p class="text-body-1 mb-6">
              Use this only if the heading was entered wrong. Every record from this deployment will say the sensor
              faced the new way. If the unit was turned, use Modify deployment on the place in use instead.
            </p>
            <!-- Keyed by the deployment: a pick remembers a measured heading, and this dialog is reused for others -->
            <HeadingPick :key="deployment.id" v-model="heading" label="Heading" :disabled="saving" class="mb-6" />
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
