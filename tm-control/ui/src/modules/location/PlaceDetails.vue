<!--
  What a place's panel says about it: whether it was imported, when it was first and last used, its events, and its
  deployments. The page asks the API for the events and deployments when the panel first opens and passes them in as
  `details` (undefined until then); `retry` asks it to try again after an error. The deployments are grouped by the
  deploy they came from: Node-RED starts every row of one config load at the same time, so rows that share `started`
  are one deploy. Newest first, so the running one is on top on a phone. Each deployment of a used place or the place
  in use has "Correct bearing", which asks the page to open its correction dialog (`correctBearing`).
-->
<script setup lang="ts">
import type { components } from '../../api/schema'
import { ago } from '../../components/relative-time'
import { bearingTitle } from './coordinates'

type SurveyOut = components['schemas']['SurveyOut']
type EventsOut = components['schemas']['EventsOut']
type DeploymentOut = components['schemas']['DeploymentOut']

export interface Details {
  events: EventsOut | null
  deployments: DeploymentOut[] | null
  error: string
}

defineProps<{
  place: SurveyOut
  details: Details | undefined
  nodered: boolean // whether Node-RED answered the usage counts
}>()
const emit = defineEmits<{ retry: []; correctBearing: [deployment: DeploymentOut] }>()

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

function eventsLine(events: EventsOut) {
  if (events.event_count === 0 || events.first_event === null || events.last_event === null) {
    return 'No events recorded at this place.'
  }
  const count = events.event_count === 1 ? '1 event' : `${events.event_count} events`
  return `${count} from ${day(events.first_event * 1000)} to ${day(events.last_event * 1000)}`
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

// The rows grouped by their exact start, newest deploy first; rows with no start, last
function deploysOf(deployments: DeploymentOut[]): Deploy[] {
  const groups = new Map<number | null, DeploymentOut[]>()
  for (const deployment of deployments) {
    groups.set(deployment.started, [...(groups.get(deployment.started) ?? []), deployment])
  }
  const deploys = [...groups].map(([started, rows]) => {
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
    <template v-if="nodered">
      <v-row v-if="place.deployment_count > 0" dense class="mb-4">
        <v-col v-for="fact in usedFacts(place)" :key="fact.label" cols="6" sm="4">
          <div class="text-body-2 text-secondary">{{ fact.label }}</div>
          <div class="text-body-1">{{ fact.value }}</div>
        </v-col>
      </v-row>
      <p v-else class="text-body-1 mb-4">Not used yet.</p>
    </template>

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
                    <span class="text-body-2 text-secondary">
                      {{ deployment.bearing ? `Facing ${bearingTitle(deployment.bearing)}` : 'No bearing set' }}
                    </span>
                    <v-btn
                      v-if="place.status !== 'planned'"
                      variant="text"
                      color="primary"
                      min-height="44"
                      @click="emit('correctBearing', deployment)"
                    >
                      Correct bearing
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
  </div>
</template>

<style scoped>
.deployments {
  list-style: none;
  padding: 0;
}
</style>
