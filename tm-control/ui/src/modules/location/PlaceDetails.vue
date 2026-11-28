<!--
  What a place's panel says about it: whether it was imported, when it was first and last used, its events, and its
  deployments. The page asks the API for the events and deployments when the panel first opens and passes them in as
  `details` (undefined until then); `retry` asks it to try again after an error. The deployments are grouped by the
  deploy they came from: Node-RED starts every row of one config load together, at the same instant in this version
  and a millisecond or so apart in released ones, so rows that start within a second of a deploy's first row are that
  deploy. Newest first, so the running one is on top on a phone. Each deployment's line says what is recorded: its
  heading, and the height and the tilt in the unit the Mounting page last used. A deployment that has ended has
  "Correct heading", which asks the page to open its correction dialog (`correctHeading`); a running one at the place
  in use is changed on the Mounting page instead, so it has "Mounting", unless its sensor has no section there
  (`mountingSensors`: a sensor disabled since its deployment started keeps its open row), which keeps Correct heading.
  A used place and the place in use also show their time zone beside First used and Last used ("Not set" for none).
  That fact comes from the control app, so it shows when Node-RED didn't answer too. Under the facts, only the place in
  use gets a line when its time zone is missing, or differs from the unit's clock (`clockTimeZone`, null when unknown);
  neither is an error, so both are plain text.
  After the deployments comes the place's reference pictures, "Reference pictures (n)", which PlacePictures lists. The
  page loads them (`pictures`, with `picturesError` and `retryPictures`) and passes the enabled cameras' keys for the
  place in use (`cameras`); a delete or a keep emits `picturesChanged`. They don't depend on Node-RED, so they show
  when it didn't answer.
-->
<script setup lang="ts">
import { computed } from 'vue'
import type { components } from '../../api/schema'
import { ago } from '../../components/relative-time'
import { facing } from './heading'
import { savedUnit, shown } from './lengths'
import PlacePictures from './PlacePictures.vue'
import type { PictureOut } from './pictures'

type SurveyOut = components['schemas']['SurveyOut']
type EventsOut = components['schemas']['EventsOut']
type DeploymentOut = components['schemas']['DeploymentOut']
type SensorKey = components['schemas']['SensorKey']

export interface Details {
  events: EventsOut | null
  deployments: DeploymentOut[] | null
  error: string
}

const props = defineProps<{
  place: SurveyOut
  details: Details | undefined
  nodered: boolean // whether Node-RED answered the usage counts
  clockTimeZone: string | null // the unit's clock's time zone; null when unknown
  mountingSensors?: SensorKey[] | null // the sensors the Mounting page has a section for; unknown when left out
  pictures?: PictureOut[] // the place's stored reference pictures; undefined until loaded
  picturesError?: string // why they couldn't be loaded
  cameras?: string[] // the enabled cameras' keys at the place in use; none elsewhere
}>()
const emit = defineEmits<{
  retry: []
  correctHeading: [deployment: DeploymentOut]
  retryPictures: []
  picturesChanged: []
}>()

// A time in ms as a date and time in the browser's words, such as "Oct 28, 2026, 2:32 PM"
function dateTime(ms: number) {
  return new Date(ms).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}

function day(ms: number) {
  return new Date(ms).toLocaleDateString(undefined, { dateStyle: 'medium' })
}

function since(ms: number | null) {
  return ms === null ? 'Unknown' : ago((Date.now() - ms) / 1000)
}

function usedFacts(place: SurveyOut) {
  return [
    { label: 'First used', value: since(place.first_used) },
    { label: 'Last used', value: place.open_count > 0 ? 'In use now' : since(place.last_used) },
  ]
}

// First used, Last used, and the time zone, as far as they are known. A planned place shows its time zone on its Edit
// form instead, and the used counts come from Node-RED.
const facts = computed(() => [
  ...(props.nodered && props.place.deployment_count > 0 ? usedFacts(props.place) : []),
  ...(props.place.status === 'planned'
    ? []
    : [{ label: 'Time zone', value: props.place.timezone ?? 'Not set' }]),
])

const inUse = computed(() => props.place.status === 'in_use')

// The heading's count: the loaded list's, else the place's own count from the list of places
const pictureCount = computed(() => props.pictures?.length ?? props.place.pictures)

// The place in use has none, or has another than the unit's clock; nothing is said when the clock's is unknown
const clockDiffers = computed(
  () =>
    inUse.value &&
    props.place.timezone !== null &&
    props.clockTimeZone !== null &&
    props.place.timezone !== props.clockTimeZone,
)

function eventsLine(events: EventsOut) {
  if (events.event_count === 0 || events.first_event === null || events.last_event === null) {
    return 'No events recorded at this place.'
  }
  const count = events.event_count === 1 ? '1 event' : `${events.event_count} events`
  return `${count} from ${day(events.first_event * 1000)} to ${day(events.last_event * 1000)}`
}

// What a deployment recorded, in one line: "Facing NE (40°) · 7.0 ft up · tilted 15°"
const unit = savedUnit()

function recorded(deployment: DeploymentOut) {
  const parts = [deployment.heading_deg === null ? 'No heading set' : `Facing ${facing(deployment.heading_deg)}`]
  if (deployment.height_m !== null) parts.push(`${shown(deployment.height_m, unit)} ${unit} up`)
  if (deployment.pitch_deg !== null) parts.push(`tilted ${deployment.pitch_deg}°`)
  return parts.join(' · ')
}

// A running deployment at the place in use is changed on the Mounting page, when that page has its sensor
function onMountingPage(deployment: DeploymentOut) {
  if (deployment.ended !== null || props.place.status !== 'in_use') return false
  const listed = props.mountingSensors
  return (
    !listed ||
    listed.some((sensor) => sensor.sensor_type === deployment.sensor_type && sensor.sensor_name === deployment.sensor_name)
  )
}

// The sensors of a deploy in this order, so a camera comes first and its radar under it
const SENSOR_ORDER = ['cameras', 'radars', 'airquality_monitors']

function sensorRank(deployment: DeploymentOut) {
  const rank = SENSOR_ORDER.indexOf(deployment.sensor_type)
  return rank === -1 ? SENSOR_ORDER.length : rank
}

interface Deploy {
  started: number | null
  ended: number | null // the latest end, once every sensor has ended
  running: boolean
  rows: DeploymentOut[]
}

// How far after a deploy's first row another row can start and still be that deploy, in ms
const SAME_DEPLOY = 1000

function sameDeploy(first: number | null, started: number | null) {
  if (first === null || started === null) return first === started
  return started - first < SAME_DEPLOY
}

// The rows grouped by the deploy they came from, newest first; rows with no start, last
function deploysOf(deployments: DeploymentOut[]): Deploy[] {
  const groups: { started: number | null; rows: DeploymentOut[] }[] = []
  const byStart = [...deployments].sort((a, b) => (a.started ?? Infinity) - (b.started ?? Infinity))
  for (const deployment of byStart) {
    const last = groups[groups.length - 1]
    if (last && sameDeploy(last.started, deployment.started)) last.rows.push(deployment)
    else groups.push({ started: deployment.started, rows: [deployment] })
  }
  const deploys = groups.map(({ started, rows }) => {
    const ends = rows.flatMap((row) => (row.ended === null ? [] : [row.ended]))
    const running = ends.length < rows.length
    return {
      started,
      ended: running ? null : Math.max(...ends),
      running,
      rows: [...rows].sort((a, b) => sensorRank(a) - sensorRank(b) || a.sensor_name.localeCompare(b.sensor_name)),
    }
  })
  return deploys.sort((a, b) => (b.started ?? -Infinity) - (a.started ?? -Infinity))
}

// A deploy's heading. One that started and ended on the same day names the day once.
function deployTitle(deploy: Deploy) {
  if (deploy.started === null) return 'Unknown start'
  const start = `Deployed ${dateTime(deploy.started)}`
  if (deploy.running) return `${start}, running now`
  const end = deploy.ended as number
  const sameDay = day(deploy.started) === day(end)
  return `${start} to ${sameDay ? new Date(end).toLocaleTimeString(undefined, { timeStyle: 'short' }) : dateTime(end)}`
}

// A row's own end, only when the deploy's heading doesn't already say it
function ownEnd(deployment: DeploymentOut, deploy: Deploy) {
  if (deployment.ended === null || (deploy.started !== null && deployment.ended === deploy.ended)) return ''
  return `Ended ${dateTime(deployment.ended)}`
}

// A radar reads as attached to the camera deployed with it
function attached(deployment: DeploymentOut, deploy: Deploy) {
  return deployment.sensor_type === 'radars' && deploy.rows.some((row) => row.sensor_type === 'cameras')
}
</script>

<template>
  <div>
    <p v-if="place.imported" class="text-body-1 mb-4">Imported from your previous settings</p>
    <p v-if="nodered && place.deployment_count === 0" class="text-body-1 mb-4">Not used yet.</p>
    <v-row v-if="facts.length" dense class="mb-4">
      <v-col v-for="fact in facts" :key="fact.label" :cols="fact.label === 'Time zone' ? 12 : 6" sm="4">
        <div class="text-body-2 text-secondary">{{ fact.label }}</div>
        <div class="text-body-1 text-break">{{ fact.value }}</div>
      </v-col>
    </v-row>
    <p v-if="inUse && place.timezone === null" class="text-body-1 mb-4">
      This place has no time zone. Set one so its data can be read in local time.
    </p>
    <p v-else-if="clockDiffers" class="text-body-1 mb-4">
      The unit's clock is set to {{ clockTimeZone }}. Change it on
      <router-link to="/time" class="text-primary">Date and time</router-link>.
    </p>

    <template v-if="details">
      <v-alert v-if="details.error" type="error" class="mb-4">
        {{ details.error }}
        <template #append>
          <v-btn variant="text" @click="emit('retry')">Try again</v-btn>
        </template>
      </v-alert>
      <v-progress-linear v-else-if="!details.events" indeterminate color="primary" class="mb-4" />
      <template v-else>
        <p class="text-body-1 mb-4">{{ eventsLine(details.events) }}</p>
        <template v-if="details.deployments?.length">
          <h4 class="text-body-1 font-weight-medium mb-2">Deployments ({{ details.deployments.length }})</h4>
          <ul class="deployments d-flex flex-column ga-5 mb-6">
            <li
              v-for="deploy in deploysOf(details.deployments)"
              :key="deploy.started ?? 'unknown'"
              :class="['border-s-md ps-3', deploy.running && 'border-primary border-opacity-100']"
              data-deploy
            >
              <div class="text-body-2 font-weight-medium mb-1" data-deploy-title>{{ deployTitle(deploy) }}</div>
              <ul class="deployments d-flex flex-column ga-2">
                <li
                  v-for="deployment in deploy.rows"
                  :key="deployment.id"
                  :class="{ 'ps-4': attached(deployment, deploy) }"
                  :data-deployment="deployment.id"
                >
                  <div class="text-body-1 text-break">{{ deployment.sensor_name }}</div>
                  <div class="d-flex flex-wrap align-center gc-2">
                    <span class="text-body-2 text-secondary">{{ recorded(deployment) }}</span>
                    <v-btn
                      v-if="onMountingPage(deployment)"
                      variant="text"
                      color="primary"
                      min-height="44"
                      to="/location/mounting"
                    >
                      Mounting
                    </v-btn>
                    <v-btn
                      v-else-if="place.status !== 'planned'"
                      variant="text"
                      color="primary"
                      min-height="44"
                      @click="emit('correctHeading', deployment)"
                    >
                      Correct heading
                    </v-btn>
                  </div>
                  <div v-if="ownEnd(deployment, deploy)" class="text-body-2 text-secondary">
                    {{ ownEnd(deployment, deploy) }}
                  </div>
                </li>
              </ul>
            </li>
          </ul>
        </template>
      </template>
    </template>

    <h4 class="text-body-1 font-weight-medium mb-2" data-pictures>Reference pictures ({{ pictureCount }})</h4>
    <PlacePictures
      :place="place"
      :pictures="pictures"
      :error="picturesError ?? ''"
      :cameras="cameras ?? []"
      class="mb-4"
      @changed="emit('picturesChanged')"
      @retry="emit('retryPictures')"
    />
  </div>
</template>

<style scoped>
.deployments {
  list-style: none;
  padding: 0;
}
</style>
