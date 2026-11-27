<!--
  The review step before a deploy (POST /surveys/{id}/deploy), the content of the page's dialog, named by the place's
  status (deployWords: Deploy here or Re-deploy here). It shows what deploying does rather than how: for each enabled
  sensor that a new deployment starts, with its heading then and the one to deploy with (which can be changed here);
  what the database stores for the place; what's shared. Deploy sends every sensor's heading and waits, inside the
  request, for Node-RED to start the deployments. Then the review gives way to the result: the new deployment ids to
  copy, or, when Node-RED hasn't reloaded the settings yet, a line that says the deploy is done and shouldn't be
  repeated; and the next step, the Mounting page, which says when the place has values from last time waiting there.
  The place in use is never reviewed here: its mounting and headings change on the Mounting page.

  Emits `deployed` once the API has answered, or once the connection dropped while it waited (the settings may be
  saved by then); `stale` when the API refused because something changed since the page loaded (409), so the page
  loads the places again; and `close`.
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ApiError, api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import { copyText } from '../../components/clipboard'
import { PRECISIONS, deployWords, formatStored, startingHeadings } from './coordinates'
import { facing } from './heading'
import HeadingPick from './HeadingPick.vue'

type PlacesState = components['schemas']['PlacesState']
type SurveyOut = components['schemas']['SurveyOut']
type DeployOut = components['schemas']['DeployOut']

const props = defineProps<{ place: SurveyOut; state: PlacesState }>()
const emit = defineEmits<{ deployed: []; stale: []; close: [] }>()

// The state as it was when the review opened, as plain constants: not reactive, on purpose. The page loads the state
// again after the deploy, while the result shows, and the review must not change under it.
const sensors = props.state.sensors
const precision = props.state.precision
const sharing = props.state.sharing
const words = deployWords(props.place.status)

// The heading to deploy each sensor with: the place's own, else the sensor's current one. Moving to another place
// starts a new deployment for every sensor.
const chosen = ref(startingHeadings(sensors, props.place))

function was(heading: number | null) {
  return heading === null ? 'not set' : facing(heading)
}

// What the database stores for the place, as the API rounded it; null when it stores nothing
const stored = computed(() => {
  const { stored_lat: lat, stored_lon: lon } = props.place
  if (precision === 'none' || lat === null || lon === null) return null
  const places = PRECISIONS.find((choice) => choice.value === precision)?.places
  return formatStored(lat, lon, places)
})

const SHARING_LINES = {
  none: 'Not sharing',
  data: 'Sharing: data, rounded location',
  exact: 'Sharing: data and the exact location',
}
const sharingLine = SHARING_LINES[sharing]

const deploying = ref(false)
const error = ref('')
const result = ref<DeployOut | null>(null)
const dropped = ref(false) // the connection dropped while the API waited: the settings may be saved
const reviewing = computed(() => !result.value && !dropped.value)

// The next step after a deploy, the Mounting page; a place with values from last time says they wait there
const nextStep = computed(() =>
  result.value?.previous.length
    ? "This place has mounting values from the last time the unit was here. They aren't recorded until you confirm them."
    : 'Next, record how the unit is mounted.',
)

async function deploy() {
  deploying.value = true
  error.value = ''
  try {
    const { data } = await api.POST('/api/v1/surveys/{survey_id}/deploy', {
      params: { path: { survey_id: props.place.id } },
      body: { headings: chosen.value },
    })
    result.value = data as DeployOut
    emit('deployed')
  } catch (failure) {
    if (failure instanceof ApiError && failure.status === 0) {
      // Not the client's "try again": config.yml may be written already, and a second deploy would write it again
      dropped.value = true
      emit('deployed')
      return
    }
    error.value = messageOf(failure)
    if (failure instanceof ApiError && failure.status === 409) emit('stale')
  } finally {
    deploying.value = false
  }
}

// Copying one deployment id; "Copied." shows beside its button for two seconds
const copied = ref<{ id: string; text: string } | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined
onBeforeUnmount(() => clearTimeout(timer))

async function copy(id: string) {
  clearTimeout(timer)
  if (await copyText(id)) {
    copied.value = { id, text: 'Copied.' }
    timer = setTimeout(() => (copied.value = null), 2000)
  } else {
    copied.value = { id, text: "This browser didn't let the page copy." }
  }
}
</script>

<template>
  <v-card color="surface" rounded="lg">
    <v-card-title class="text-h6 text-wrap pt-4">{{ words.action }}</v-card-title>
    <v-card-text>
      <p class="text-subtitle-1 font-weight-medium text-break">{{ place.description ?? 'No description' }}</p>
      <p class="text-body-2 text-secondary mb-6">{{ place.id }}</p>

      <!-- The review: what each sensor does, then what's stored and shared -->
      <template v-if="reviewing">
        <ul class="sensors d-flex flex-column ga-5 mb-6">
          <li
            v-for="(sensor, index) in sensors"
            :key="`${sensor.sensor_type}/${sensor.sensor_name}`"
            :data-sensor="sensor.sensor_name"
          >
            <div class="text-body-1 font-weight-medium text-break">{{ sensor.sensor_name }}</div>
            <div class="text-body-2 text-primary">New deployment starts</div>
            <div class="d-flex flex-wrap align-center ga-2 mt-2">
              <span class="text-body-1 text-no-wrap">Was {{ was(sensor.heading_deg) }}, now</span>
              <HeadingPick
                v-model="chosen[index].heading_deg"
                :aria-label="`Heading to deploy ${sensor.sensor_name} with`"
                :disabled="deploying"
                density="compact"
                class="heading"
              />
            </div>
          </li>
        </ul>
        <!-- The pair stays on one line: "45.0," at the end of one line and "-122.0" on the next reads as two values -->
        <p v-if="stored" class="text-body-1">
          Stored in the database: <span class="text-no-wrap">{{ stored }}</span>
        </p>
        <p v-else class="text-body-1">Nothing stored in the database</p>
        <p class="text-body-1">{{ sharingLine }}</p>
        <p class="text-body-1 mt-4">Counts from now on attach to the new deployment.</p>

        <div v-if="deploying" role="status" class="mt-6">
          <v-progress-linear indeterminate color="primary" class="mb-2" />
          <p class="text-body-2 text-secondary">Waiting for Node-RED to reload the settings</p>
        </div>
        <v-alert v-if="error" type="error" class="mt-4">{{ error }}</v-alert>
      </template>

      <!-- The result -->
      <v-alert v-else-if="dropped" type="warning">
        The connection dropped before the answer came. The settings may already be saved: close this and check the
        place before deploying again.
      </v-alert>
      <template v-else-if="result">
        <v-alert v-if="!result.reloaded" type="warning">
          The settings are saved. Node-RED hasn't reloaded them yet; the deployments appear once it does. Don't deploy
          again.
        </v-alert>
        <template v-else>
          <v-alert type="success" class="mb-4">Deployed. Counts from now on attach to these deployments.</v-alert>
          <ul class="sensors d-flex flex-column ga-4">
            <li v-for="deployment in result.deployments" :key="deployment.id">
              <div class="text-body-2 text-secondary text-break">{{ deployment.sensor_name }}</div>
              <div class="d-flex flex-wrap align-center ga-3">
                <span class="text-body-1 text-break">{{ deployment.id }}</span>
                <v-btn variant="outlined" color="primary" min-height="44" @click="copy(deployment.id)">Copy</v-btn>
                <span role="status" class="text-body-2 text-secondary">
                  {{ copied?.id === deployment.id ? copied.text : '' }}
                </span>
              </div>
            </li>
          </ul>
        </template>
        <div class="mt-6">
          <p class="text-body-1 mb-3">{{ nextStep }}</p>
          <v-btn variant="outlined" color="primary" min-height="44" to="/location/mounting">Mounting</v-btn>
        </div>
      </template>
    </v-card-text>
    <v-card-actions class="px-4 pb-4">
      <v-spacer />
      <template v-if="reviewing">
        <v-btn variant="text" min-height="44" :disabled="deploying" @click="emit('close')">Cancel</v-btn>
        <v-btn color="primary" variant="flat" min-height="44" :loading="deploying" @click="deploy">
          {{ words.confirm }}
        </v-btn>
      </template>
      <v-btn v-else color="primary" variant="flat" min-height="44" @click="emit('close')">Close</v-btn>
    </v-card-actions>
  </v-card>
</template>

<style scoped>
.sensors {
  list-style: none;
  padding: 0;
}

/* Wide enough for "NE (40°)" and the menu's arrow. The row wraps rather than squeeze it when the words before it are
   long, as "Was NE (40°), now" is on a phone. */
.heading {
  flex: none;
  width: 11rem;
}
</style>
