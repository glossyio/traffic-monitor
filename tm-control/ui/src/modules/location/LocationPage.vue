<!--
  The Location page (GET /surveys), for admins only: the place the unit is at now, the precision the database stores
  locations at (PUT /surveys/precision), and the places this unit knows, one panel each. Opening a panel asks for the
  place's events and deployments (GET /surveys/{id}/events and /deployments). A place can be added, and a planned one
  edited, in PlaceForm's dialog. "Deploy here" opens DeployReview, which moves the unit to a planned or used place,
  or, on the place in use, records a turn of the unit (a bearing changed). A planned or used place can be deleted
  (DELETE /surveys/{id}) after a confirmation; the place in use can't.
-->
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { ago } from '../../components/relative-time'
import StatusCard from '../../components/StatusCard.vue'
import { PRECISIONS, bearingTitle, formatExact, formatStored, isCoarser, type Precision } from './coordinates'
import DeployReview from './DeployReview.vue'
import PlaceDetails, { type Details } from './PlaceDetails.vue'
import PlaceForm from './PlaceForm.vue'

type PlacesState = components['schemas']['PlacesState']
type SurveyOut = components['schemas']['SurveyOut']
type EventsOut = components['schemas']['EventsOut']
type DeploymentOut = components['schemas']['DeploymentOut']

const STATUS: Record<string, string> = { in_use: 'In use', planned: 'Planned', used: 'Used' }

const RECONCILE: Record<string, string> = {
  waiting_nodered:
    "Node-RED hasn't answered yet, so past places may be missing. The page checks again when you reload it.",
  config_unreadable:
    "Node-RED's config.yml couldn't be read, so the place in use may be missing. The Location check on the Status " +
    "page says what's wrong with the file.",
}

const state = ref<PlacesState | null>(null)
const loadError = ref('')

function titleOf(place: SurveyOut) {
  return place.description ?? 'No description'
}

// The stored coordinates, padded to the precision's decimal places ("45.0", not "45")
function stored(place: SurveyOut) {
  const places = PRECISIONS.find((choice) => choice.value === state.value?.precision)?.places
  return formatStored(place.stored_lat, place.stored_lon, places)
}

function since(ms: number | null) {
  return ms === null ? 'Unknown' : ago((Date.now() - ms) / 1000)
}

// The place in use, as the card at the top
const inUse = computed(() => state.value?.surveys.find((place) => place.id === state.value?.in_use) ?? null)

const cardItems = computed(() => {
  const place = inUse.value
  if (!place || !state.value) return []
  return [
    { label: 'Stored in the database', value: stored(place) },
    { label: 'Exact location', value: formatExact(place.lat, place.lon) },
    { label: 'Sharing', value: state.value.sharing === 'data' ? 'Sharing: data' : 'Not sharing' },
    ...state.value.sensors.map((sensor) => ({
      label: `Bearing, ${sensor.sensor_name}`,
      value: bearingTitle(sensor.bearing),
    })),
  ]
})

// Only the place the device made at first run, with no coordinates: most units never need more
const onlyDefault = computed(() => state.value?.surveys.length === 1 && state.value.surveys[0].lat === null)

// The precision. Rounding the rows already stored is offered only for a coarser choice: a finer one applies from
// the next deployment, because the rows can't get back what was rounded away.
const precisionChoice = ref<Precision>('2')
const roundStored = ref(false)
const offerRound = computed(() => state.value !== null && isCoarser(precisionChoice.value, state.value.precision))
const finer = computed(() => state.value !== null && isCoarser(state.value.precision, precisionChoice.value))
const savingPrecision = ref(false)
const precisionResult = ref<{ text: string; error: boolean } | null>(null)
const confirmRound = ref(false)

function precisionChanged() {
  roundStored.value = false
  precisionResult.value = null
}

function askToSavePrecision() {
  if (offerRound.value && roundStored.value) confirmRound.value = true
  else void savePrecision()
}

async function savePrecision() {
  const round = offerRound.value && roundStored.value
  savingPrecision.value = true
  precisionResult.value = null
  try {
    const { data } = await api.PUT('/api/v1/surveys/precision', {
      body: { precision: precisionChoice.value, round_stored: round },
    })
    state.value = data as PlacesState
    precisionChoice.value = state.value.precision
    roundStored.value = false
    precisionResult.value = { text: round ? 'Saved. The rows already stored are rounded.' : 'Saved.', error: false }
  } catch (error) {
    precisionResult.value = { text: messageOf(error), error: true }
  } finally {
    savingPrecision.value = false
  }
}

// The open panels, by place id. Opening a place's panel the first time asks for its events and deployments.
const UNASSIGNED = 'unassigned'
const open = ref<string[]>([])
const details = reactive<Record<string, Details>>({})

async function loadDetails(id: string) {
  details[id] = { events: null, deployments: null, error: '' }
  const path = { params: { path: { survey_id: id } } }
  try {
    const [events, deployments] = await Promise.all([
      api.GET('/api/v1/surveys/{survey_id}/events', path),
      api.GET('/api/v1/surveys/{survey_id}/deployments', path),
    ])
    details[id].events = events.data as EventsOut
    details[id].deployments = (deployments.data as { deployments: DeploymentOut[] }).deployments
  } catch (error) {
    details[id].error = messageOf(error)
  }
}

watch(open, (ids) => {
  for (const id of ids) if (id !== UNASSIGNED && !(id in details)) void loadDetails(id)
})

// Deleting a place, after a confirmation. A used place's exact location goes with it; the database keeps the
// rounded location stored with its rows.
const deleting = ref<SurveyOut | null>(null)
const deleteOpen = computed({
  get: () => deleting.value !== null,
  set: (value: boolean) => {
    if (!value) deleting.value = null
  },
})
const deleteTitle = computed(() => {
  const place = deleting.value
  if (!place) return ''
  return place.description ? `Delete "${place.description}"?` : `Delete place ${place.id}?`
})
const deleteText = computed(() => {
  if (deleting.value?.status === 'used') {
    return (
      'Its exact location is deleted with it. The database keeps the rounded location stored with each of its ' +
      "records. This can't be undone."
    )
  }
  return "It's removed from the list of places. This can't be undone."
})
const working = ref<string | null>(null) // the id of the place being deleted
const placeErrors = reactive<Record<string, string>>({})
const listResult = ref('')

async function deletePlace() {
  const place = deleting.value
  if (!place) return
  working.value = place.id
  listResult.value = ''
  placeErrors[place.id] = ''
  try {
    await api.DELETE('/api/v1/surveys/{survey_id}', { params: { path: { survey_id: place.id } } })
    listResult.value = `Deleted ${place.description ? `"${place.description}"` : `place ${place.id}`}.`
    await load()
  } catch (error) {
    placeErrors[place.id] = messageOf(error)
  } finally {
    working.value = null
  }
}

// Adding a place, or editing a planned one, in PlaceForm's dialog
const formOpen = ref(false)
const editing = ref<SurveyOut | undefined>(undefined)

function openForm(place?: SurveyOut) {
  editing.value = place
  formOpen.value = true
}

// Deploying to a place, after DeployReview's review step. Once deployed, the list and the open panels' deployments
// are loaded again: the place is in use now, and the one it replaced has ended its deployments. `deployTo` keeps the
// last place after the dialog closes, so the dialog doesn't empty while it fades out; `reviews` counts the openings,
// so each one starts a fresh review.
const deployOpen = ref(false)
const deployTo = ref<SurveyOut | null>(null)
const reviews = ref(0)

function openReview(place: SurveyOut) {
  deployTo.value = place
  reviews.value += 1
  deployOpen.value = true
}

async function deployed() {
  await load()
  for (const id of Object.keys(details)) delete details[id]
  for (const id of open.value) if (id !== UNASSIGNED) void loadDetails(id)
}

// The places, on opening the page and after a change. The precision's choice follows the device's; the open panels
// stay open, but for a place that's gone.
async function load() {
  loadError.value = ''
  try {
    const { data } = await api.GET('/api/v1/surveys')
    state.value = data as PlacesState
    precisionChoice.value = state.value.precision
    // Keep open only the panels whose place is still listed
    open.value = open.value.filter((id) => id === UNASSIGNED || state.value?.surveys.some((place) => place.id === id))
  } catch (error) {
    loadError.value = messageOf(error)
  }
}

onMounted(load)
</script>

<template>
  <div>
    <h1 class="text-h5 text-primary mb-6">Location</h1>

    <v-alert v-if="loadError" type="error" class="mb-6">
      {{ loadError }}
      <template #append>
        <v-btn variant="text" @click="load">Try again</v-btn>
      </template>
    </v-alert>
    <v-progress-linear v-else-if="!state" indeterminate color="primary" />

    <template v-if="state">
      <v-alert v-if="state.reconcile !== 'done'" type="warning" class="mb-6">{{ RECONCILE[state.reconcile] }}</v-alert>
      <v-alert v-else-if="!state.nodered" type="warning" class="mb-6">
        Node-RED didn't answer, so the page can't say when each place was used.
      </v-alert>

      <StatusCard
        v-if="inUse"
        :title="titleOf(inUse)"
        :subtitle="['In use', inUse.id]"
        :items="cardItems"
      />
      <p v-else class="text-body-1">No place is in use.</p>

      <section class="mt-10">
        <h2 class="text-h6 mb-2">Precision</h2>
        <p class="text-body-1 mb-4">
          How precisely the database records where the unit is. The exact location is kept only on this device, outside
          the database, so you can still export it in full later. Exporting it is coming in a later update.
        </p>
        <v-radio-group v-model="precisionChoice" hide-details @update:model-value="precisionChanged">
          <v-radio v-for="choice in PRECISIONS" :key="choice.value" :value="choice.value" :label="choice.title" />
        </v-radio-group>
        <template v-if="offerRound">
          <v-checkbox v-model="roundStored" label="Also round the rows already stored" hide-details class="mt-2" />
          <p class="text-body-2 text-secondary">
            The deployments running now take the new precision at once. Older rows keep theirs unless you tick the
            box.
          </p>
        </template>
        <p v-if="finer" class="text-body-2 text-secondary mt-2">
          A finer precision applies from the next deployment. The rows already stored stay as they are.
        </p>
        <v-btn
          color="primary"
          size="large"
          class="mt-4"
          :loading="savingPrecision"
          :disabled="precisionChoice === state.precision"
          @click="askToSavePrecision"
        >
          Save
        </v-btn>
        <v-alert v-if="precisionResult?.error" type="error" class="mt-4">{{ precisionResult.text }}</v-alert>
        <p v-else-if="precisionResult" class="text-body-1 mt-4">{{ precisionResult.text }}</p>
      </section>

      <section class="mt-10">
        <h2 class="text-h6 mb-2">Places</h2>
        <p v-if="onlyDefault" class="text-body-1 mb-4">
          This unit records against one place. Add a location only if you plan to move the unit or share data.
        </p>
        <div class="d-flex flex-wrap ga-3 mb-4">
          <v-btn variant="outlined" color="primary" size="large" @click="openForm()">Add a place</v-btn>
          <v-btn variant="outlined" color="primary" size="large">Import places</v-btn>
        </div>
        <p v-if="listResult" class="text-body-1 mb-4">{{ listResult }}</p>

        <!-- One panel per place, in the API's order: in use, then planned, then used. Each title, a button, goes inside
             an h3, so the headings stay headings for screen readers, as on the Detection page. -->
        <v-expansion-panels v-model="open" multiple flat bg-color="background" class="ga-3">
          <v-expansion-panel v-for="place in state.surveys" :key="place.id" :value="place.id" class="border">
            <h3 class="text-body-1">
              <v-expansion-panel-title>
                <span class="d-flex flex-column ga-1">
                  <span class="d-flex flex-wrap align-center ga-2">
                    <span class="text-subtitle-1 font-weight-medium">{{ titleOf(place) }}</span>
                    <v-chip
                      size="small"
                      variant="outlined"
                      :color="place.status === 'in_use' ? 'primary' : undefined"
                    >
                      {{ STATUS[place.status] ?? place.status }}
                    </v-chip>
                  </span>
                  <span class="text-body-2 text-secondary">{{ place.id }}</span>
                  <span class="text-body-2">{{ stored(place) }}</span>
                </span>
              </v-expansion-panel-title>
            </h3>
            <v-expansion-panel-text>
              <PlaceDetails
                :place="place"
                :details="details[place.id]"
                :nodered="state.nodered"
                @retry="loadDetails(place.id)"
              />
              <div class="d-flex flex-wrap ga-3">
                <v-btn color="primary" size="large" :disabled="working !== null" @click="openReview(place)">
                  Deploy here
                </v-btn>
                <v-btn
                  v-if="place.status === 'planned'"
                  variant="outlined"
                  color="primary"
                  size="large"
                  @click="openForm(place)"
                >
                  Edit
                </v-btn>
                <v-btn v-if="place.status !== 'planned'" variant="outlined" color="primary" size="large">
                  Correct location
                </v-btn>
                <v-btn
                  v-if="place.status !== 'in_use'"
                  variant="outlined"
                  color="primary"
                  size="large"
                  :loading="working === place.id"
                  :disabled="working !== null"
                  @click="deleting = place"
                >
                  Delete
                </v-btn>
              </div>
              <v-alert v-if="placeErrors[place.id]" type="error" class="mt-4">{{ placeErrors[place.id] }}</v-alert>
            </v-expansion-panel-text>
          </v-expansion-panel>

          <!-- Deployments Node-RED recorded before the unit had any place: counted, not listed -->
          <v-expansion-panel v-if="state.unassigned" :value="UNASSIGNED" class="border">
            <h3 class="text-body-1">
              <v-expansion-panel-title>
                <span class="d-flex flex-column ga-1">
                  <span class="text-subtitle-1 font-weight-medium">Before any place was recorded</span>
                  <span class="text-body-2 text-secondary">
                    {{ state.unassigned.deployment_count }}
                    {{ state.unassigned.deployment_count === 1 ? 'deployment' : 'deployments' }}
                  </span>
                </span>
              </v-expansion-panel-title>
            </h3>
            <v-expansion-panel-text>
              <p class="text-body-1 mb-4">
                These deployments were recorded before the unit had a place, so they belong to none. The database keeps
                them as they are.
              </p>
              <v-row dense>
                <v-col cols="6" sm="4">
                  <div class="text-body-2 text-secondary">First started</div>
                  <div class="text-body-1">{{ since(state.unassigned.first_start) }}</div>
                </v-col>
                <v-col cols="6" sm="4">
                  <div class="text-body-2 text-secondary">Last ended</div>
                  <div class="text-body-1">{{ since(state.unassigned.last_end) }}</div>
                </v-col>
              </v-row>
            </v-expansion-panel-text>
          </v-expansion-panel>
        </v-expansion-panels>
      </section>
    </template>

    <PlaceForm
      v-if="state"
      v-model:open="formOpen"
      :sensors="state.sensors"
      :survey="editing"
      @saved="load"
      @stale="load"
    />
    <!-- Persistent: a click beside the dialog doesn't close it, so a deploy that's waiting for Node-RED can't be lost -->
    <v-dialog v-model="deployOpen" persistent max-width="560" aria-label="Deploy here">
      <DeployReview
        v-if="deployTo && state"
        :key="reviews"
        :place="deployTo"
        :state="state"
        @deployed="deployed"
        @stale="load"
        @close="deployOpen = false"
      />
    </v-dialog>
    <ConfirmDialog
      v-model="confirmRound"
      title="Round the rows already stored?"
      text="Every location the database already holds is rounded to the new precision. This can't be undone."
      confirm-text="Save and round"
      @confirm="savePrecision"
    />
    <ConfirmDialog
      v-model="deleteOpen"
      :title="deleteTitle"
      :text="deleteText"
      confirm-text="Delete"
      @confirm="deletePlace"
    />
  </div>
</template>
