<!--
  The Sharing page (GET /sharing): what this device uploads and to which server, for every signed-in user, and for
  admins the form that changes it (SharingForm). A summary card says what is shared and how the server last answered.
  After a save that leaves the upload on, the page reads the state again every 5 seconds, for up to a minute, while
  the server hasn't answered yet (waiting, or Node-RED not answering), so the admin sees whether the first upload was
  taken. When the state says an upload was found on that nobody chose (review_needed), an alert says so and an admin
  can mark it reviewed (POST /sharing/reviewed).
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import { agoAt } from '../../components/relative-time'
import StatusCard from '../../components/StatusCard.vue'
import { useSession } from '../../stores/session'
import SharingForm from './SharingForm.vue'

type SharingState = components['schemas']['SharingState']

const POLL_MS = 5000
const POLL_LIMIT_MS = 60_000

// The Status page's check says the same thing
const REVIEW_TEXT =
  'This device\'s upload was turned on without a choice on the Sharing page. It shares data with the location as the ' +
  'database stores it. Review the choices.'

const session = useSession()
const route = useRoute()
const state = ref<SharingState | null>(null)
const loadError = ref('')

async function load() {
  loadError.value = ''
  try {
    const { data } = await api.GET('/api/v1/sharing')
    state.value = data as SharingState
  } catch (error) {
    loadError.value = messageOf(error)
  }
}

onMounted(async () => {
  await load()
  if (route.hash === '#token' && state.value) {
    await nextTick() // the form is on the page now
    document.getElementById('token')?.scrollIntoView?.() // jsdom, in the tests, has no scrollIntoView
  }
})

// The review: an admin has seen what an upload found on shares
const reviewing = ref(false)
const reviewError = ref('')

async function reviewed() {
  reviewing.value = true
  reviewError.value = ''
  try {
    await api.POST('/api/v1/sharing/reviewed')
    await load()
  } catch (error) {
    reviewError.value = messageOf(error)
  } finally {
    reviewing.value = false
  }
}

// Checking again after a save, until the server has answered the first upload or a minute has passed
let poll: ReturnType<typeof setInterval> | undefined
let giveUpAt = 0

function stopPolling() {
  clearInterval(poll)
  poll = undefined
}

// One check while polling. A failed read is not shown (the form above still works); the checking just stops.
async function check(): Promise<boolean> {
  try {
    const { data } = await api.GET('/api/v1/sharing')
    state.value = data as SharingState
    return true
  } catch {
    return false
  }
}

function saved(next: SharingState) {
  state.value = next
  stopPolling()
  if (!next.enabled) return
  giveUpAt = Date.now() + POLL_LIMIT_MS
  poll = setInterval(async () => {
    const read = await check()
    const answered = state.value && !['waiting', 'unknown'].includes(state.value.server.state)
    if (!read || answered || Date.now() >= giveUpAt) stopPolling()
  }, POLL_MS)
}

onBeforeUnmount(stopPolling)

const SERVER_NAMES = { maintainer: "Traffic Monitor's server", own: 'Your own server' }

// How the server last answered, in words (the Status page's check says the same, longer)
function serverStatus(server: SharingState['server']) {
  const words: Record<SharingState['server']['state'], string> = {
    off: 'Off',
    waiting: 'Waiting for the first upload',
    ok: server.at ? `Accepted an upload ${agoAt(server.at)}` : 'Accepted an upload',
    stale: server.at ? `No upload accepted since ${agoAt(server.at)}` : 'No upload accepted for a while',
    unreachable: "Can't be reached",
    refused: 'Refused the token',
    rejected: 'Refused an upload',
    server_error: 'Answered with an error',
    unknown: "Not known: Node-RED didn't answer",
  }
  return words[server.state]
}

const facts = computed(() => {
  const current = state.value
  if (!current) return []
  // the exact location goes only over https, so a server reached over http gets the stored location
  const exact = current.enabled && current.exact_location.granted && current.protocol === 'https'
  const items = [
    { label: 'Sharing', value: !current.enabled ? 'Off' : exact ? 'Data and the exact location' : 'Data' },
    { label: 'Server', value: current.target ? SERVER_NAMES[current.target] : 'Not chosen' },
    { label: 'Server status', value: serverStatus(current.server) },
  ]
  if (current.enabled) items.push({ label: 'Location sent', value: exact ? 'Exact' : 'As the database stores it' })
  return items
})
</script>

<template>
  <div>
    <h1 class="text-h5 text-primary mb-6">Sharing</h1>

    <v-alert v-if="loadError" type="error" class="mb-6">
      {{ loadError }}
      <template #append>
        <v-btn variant="text" @click="load">Try again</v-btn>
      </template>
    </v-alert>
    <v-progress-linear v-else-if="!state" indeterminate color="primary" />

    <template v-if="state">
      <v-alert v-if="state.review_needed" type="warning" class="mb-6">
        {{ REVIEW_TEXT }}
        <template v-if="session.isAdmin" #append>
          <v-btn variant="text" :loading="reviewing" :disabled="reviewing" @click="reviewed">I've reviewed this</v-btn>
        </template>
      </v-alert>
      <v-alert v-if="reviewError" type="error" class="mb-6">{{ reviewError }}</v-alert>

      <StatusCard title="Saved settings" :items="facts" />

      <section class="mt-10">
        <SharingForm v-if="session.isAdmin && state.writable" :state="state" @saved="saved" @reload="load" />
        <p v-else class="text-body-1">An administrator chooses what this device shares.</p>
      </section>
    </template>
  </div>
</template>
