<!--
  The dialog that adds a place (POST /surveys) or, given a planned `survey`, edits it (PATCH /surveys/{id}): a private
  description, the coordinates as one "latitude, longitude" field, and a heading for each enabled sensor. On a secure
  (HTTPS) page the phone can fill in the coordinates; on plain HTTP browsers don't share a location, and the form says
  so. A map button under the field picks the point on a map instead, and a line warns when fewer than four decimal
  places are typed (about 10 m): advice, never an error. The form starts over each time it opens. Emits `saved` with
  the place the API answered and whether the map set the coordinates last (typing after a pick makes it false), then
  closes; and
  `stale` when the API refused because the place changed since the page loaded (409, such as a planned place that
  was deployed meanwhile), so the page loads the places again. The place's time zone is TimeZonePick's; the body
  has no `timezone` while there is none (the clock's is unknown and none was picked), never null.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ApiError, api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import { fewDecimalsWarning, formatExact, parsePair, startingHeadings, type LatLon } from './coordinates'
import HeadingPick from './HeadingPick.vue'
import MapPickButton from './MapPickButton.vue'
import TimeZonePick from './TimeZonePick.vue'
import { startingTimeZone } from './timezones'

type SensorHeading = components['schemas']['SensorHeading']
type SurveyOut = components['schemas']['SurveyOut']
type MapSources = components['schemas']['MapSources']

const open = defineModel<boolean>('open', { required: true })
const props = defineProps<{
  sensors: SensorHeading[] // the enabled sensors, each with its heading in config.yml now
  survey?: SurveyOut // the planned place to edit; none to add one
  map: MapSources // where the map comes from; null style_url is no map
  centre: LatLon | null // where the map looks first with no point: the place in use
  timeZones: string[] // the device's list of time zones, loaded once by the page; empty when it couldn't be
  timeZonesError: string // why the list couldn't be loaded; empty when it was
  clockTimeZone: string | null // the unit's clock's time zone, which a place starts with; null when unknown
}>()
const emit = defineEmits<{ saved: [survey: SurveyOut, onMap: boolean]; stale: [] }>()

const description = ref('')
const coordinates = ref('')
const onMap = ref(false) // whether the map set the coordinates last
const headings = ref<SensorHeading[]>([])
const timeZone = ref<string | null>(null)
const openings = ref(0) // counts the openings, so each one starts the time zone control over
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
    headings.value = startingHeadings(props.sensors, survey)
    timeZone.value = startingTimeZone(survey?.timezone, props.clockTimeZone)
    openings.value += 1
    onMap.value = false
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
const fewDecimals = computed(() => fewDecimalsWarning(coordinates.value))

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
      onMap.value = false
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
    headings: headings.value,
    // Never null: the key is left out when there is no time zone, so an edit keeps the one stored and a new place
    // has none
    ...(timeZone.value === null ? {} : { timezone: timeZone.value }),
  }
  try {
    const { data } = props.survey
      ? await api.PATCH('/api/v1/surveys/{survey_id}', { params: { path: { survey_id: props.survey.id } }, body })
      : await api.POST('/api/v1/surveys', { body })
    emit('saved', data as SurveyOut, onMap.value)
    open.value = false
  } catch (failure) {
    error.value = messageOf(failure)
    if (failure instanceof ApiError && failure.status === 409) emit('stale')
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
  <v-dialog v-model="open" max-width="560" :aria-label="title">
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
            @update:model-value="onMap = false"
          />
          <p v-if="fewDecimals" class="text-body-2 text-warning mt-3 mb-2">{{ fewDecimals }}</p>
          <MapPickButton
            v-model:coordinates="coordinates"
            :map="map"
            :centre="centre"
            class="mb-2"
            @picked="onMap = true"
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

          <TimeZonePick
            :key="openings"
            v-model="timeZone"
            :time-zones="timeZones"
            :clock-time-zone="clockTimeZone"
            :error="timeZonesError"
            class="mt-6"
          />

          <template v-if="headings.length">
            <h3 class="text-subtitle-1 font-weight-medium mt-6">Which way each sensor faces here</h3>
            <!-- Keyed by the place too: a pick remembers a measured heading, and this dialog is reused for other places -->
            <HeadingPick
              v-for="sensor in headings"
              :key="`${survey?.id ?? 'new'}/${sensor.sensor_type}/${sensor.sensor_name}`"
              v-model="sensor.heading_deg"
              :label="`Facing, ${sensor.sensor_name}`"
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
