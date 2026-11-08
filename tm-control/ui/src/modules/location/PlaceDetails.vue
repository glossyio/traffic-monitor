<!--
  What a place's panel says about it: whether it was imported, when it was first and last used, its events, and its
  deployments. The page asks the API for the events and deployments when the panel first opens and passes them in as
  `details` (undefined until then); `retry` asks it to try again after an error. Each deployment of a used place or
  the place in use has "Correct bearing", which asks the page to open its correction dialog (`correctBearing`).
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

// When a deployment ran. One that started and ended on the same day names the day once.
function span(deployment: DeploymentOut) {
  if (deployment.started === null) return ''
  if (deployment.ended === null) return `Since ${dateTime(deployment.started)}`
  const end = new Date(deployment.ended)
  const sameDay = day(deployment.started) === day(deployment.ended)
  const until = sameDay ? end.toLocaleTimeString(undefined, { timeStyle: 'short' }) : dateTime(deployment.ended)
  return `${dateTime(deployment.started)} to ${until}`
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
          <ul class="deployments d-flex flex-column ga-4 mb-6">
            <li v-for="deployment in details.deployments" :key="deployment.id">
              <div class="text-body-1 text-break">{{ deployment.sensor_name }}</div>
              <div class="d-flex flex-wrap align-center column-gap-2">
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
              <div class="text-body-2 text-secondary">{{ span(deployment) }}</div>
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
