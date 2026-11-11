<!--
  The Wi-Fi networks section of the Network page (GET /network/wifi): the networks the unit has saved, in the order it
  tries them, and the ones it heard the last time it looked. Everyone sees the lists. An admin can Refresh (a scan),
  Forget a saved network, and move the ones the unit joins by itself up or down. Each of those is a root job that the
  page follows, and one runs at a time: every control is disabled while one does, and while the parent says a join is
  pending (`locked`). Forgetting the network the unit is on moves it onto its hotspot, so that asks first, and a page
  that loses the unit afterwards says why. Emits `changed` once a job is over, so the page loads the state again.
-->
<script setup lang="ts">
import { mdiArrowDown, mdiArrowUp, mdiLock, mdiRefresh } from '@mdi/js'
import { computed, onBeforeUnmount, ref } from 'vue'
import { ApiError, api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { followJob } from '../../components/jobs'
import { moved, scanAge, signalIcon, whyNot } from './networks'

type WifiNetworks = components['schemas']['WifiNetworks']
type HotspotState = components['schemas']['HotspotState']
type Saved = components['schemas']['Saved']
type Nearby = components['schemas']['Nearby']

const props = defineProps<{ wifi: WifiNetworks; hotspot: HotspotState | null; admin: boolean; locked: boolean }>()
const emit = defineEmits<{ changed: []; join: [network: Nearby] }>()

type Kind = 'scan' | 'order' | 'forget'
const running = ref<Kind | null>(null)
const forgetting = ref('') // the name, while a forget runs
const busy = computed(() => running.value !== null)
const disabled = computed(() => busy.value || props.locked)

interface Notice {
  type: 'success' | 'info' | 'warning' | 'error'
  text: string
  log?: string[]
}
const notice = ref<Notice | null>(null)

let left = false
let following: ReturnType<typeof followJob> | null = null
onBeforeUnmount(() => {
  left = true
  following?.cancel()
})

const WORKING: Record<Kind, string> = {
  scan: 'Looking for networks. Phones on the hotspot pause for a few seconds.',
  order: 'Saving the new order.',
  forget: '',
}
const working = computed(() => (running.value === 'forget' ? `Forgetting ${forgetting.value}.` : WORKING[running.value ?? 'scan']))
const FAILED: Record<Kind, string> = {
  scan: "The unit couldn't look for networks.",
  order: "The change wasn't made.",
  forget: "The change wasn't made.",
}

// Starts a root job with `start` and follows it. `lostText` is what to say when the page loses the unit after the
// device accepted the request; without it, that is an ordinary error.
async function run(kind: Kind, start: () => Promise<{ data?: unknown }>, lostText = '') {
  if (busy.value) return
  notice.value = null
  running.value = kind
  let accepted = false
  try {
    const { data } = await start()
    if (left) return
    accepted = true
    following = followJob((data as { id: string }).id)
    const job = await following.done
    if (left) return
    if (job === null) {
      notice.value = {
        type: 'warning',
        text: "The device hasn't reported whether the change was made. Reload this page in a minute to check.",
      }
    } else if (job.status === 'failed') {
      notice.value = { type: 'error', text: FAILED[kind], log: job.log }
    }
    emit('changed') // even a failed job may have changed something; the page shows what the device has
  } catch (error) {
    if (left) return
    const offline = error instanceof ApiError && error.status === 0
    if (offline && accepted && lostText) {
      notice.value = { type: 'info', text: lostText }
    } else {
      notice.value = { type: 'error', text: messageOf(error) }
      if (!offline) emit('changed') // a refusal (a stale order, a radio that is off) means the page is out of date
    }
  } finally {
    following = null
    running.value = null
    forgetting.value = ''
  }
}

function scan() {
  // The API's cross-site check wants a JSON body on every POST, even one that has nothing to say
  void run('scan', () => api.POST('/api/v1/network/wifi/scan', { body: {} as never }))
}

// The networks the unit joins by itself, in its order: only those have a place to move
const automatic = computed(() => props.wifi.saved.filter((network) => network.automatic))
const uuids = computed(() => automatic.value.map((network) => network.uuid))
const place = (network: Saved) => uuids.value.indexOf(network.uuid)
const canMoveUp = (network: Saved) => place(network) > 0
const canMoveDown = (network: Saved) => place(network) >= 0 && place(network) < uuids.value.length - 1

function move(network: Saved, by: -1 | 1) {
  const body = { uuids: moved(uuids.value, place(network), by) }
  void run('order', () => api.POST('/api/v1/network/wifi/order', { body }))
}

// Forgetting asks first, and says where the unit goes when it is the network the unit is on
const target = ref<Saved | null>(null)
const forgetOpen = ref(false)

function ask(network: Saved) {
  target.value = network
  forgetOpen.value = true
}

const forgetText = computed(() => {
  const network = target.value
  if (!network?.in_use) return 'The unit will no longer join it by itself.'
  if (props.hotspot?.enabled) {
    return `The unit is on ${network.name} now. If you forget it, the unit leaves it and starts its hotspot, ${props.hotspot.name}. Reach the unit there or by Ethernet.`
  }
  return `The unit is on ${network.name} now, and its hotspot is off. If you forget it, this unit has no wireless way in. You would need an Ethernet cable.`
})

function forget() {
  const network = target.value
  if (!network) return
  forgetting.value = network.name
  const hotspot = props.hotspot
  const lostText =
    network.in_use && hotspot?.enabled
      ? `This page lost the unit, which is expected: the unit left ${network.name}. Join its hotspot ${hotspot.name}, then open http://${hotspot.address}/.`
      : ''
  void run('forget', () => api.POST('/api/v1/network/wifi/forget', { body: { uuid: network.uuid } }), lostText)
}

const age = computed(() =>
  !props.admin && props.wifi.scanned_seconds_ago === null ? 'Not looked yet.' : scanAge(props.wifi.scanned_seconds_ago),
)
</script>

<template>
  <div>
    <v-alert v-if="!wifi.readable" type="warning" class="mb-4">
      The Wi-Fi networks couldn't be read, because the network service didn't answer.
    </v-alert>
    <p v-else-if="wifi.radio === 'none'" class="text-body-1">This unit has no built-in Wi-Fi radio.</p>
    <p v-else-if="wifi.radio === 'off'" class="text-body-1">
      The Wi-Fi radio is switched off. Turn the hotspot on to switch it on.
    </p>

    <template v-else>
      <h3 class="text-subtitle-1 font-weight-medium mb-1">Saved networks</h3>
      <p v-if="wifi.saved.length" class="text-body-2 text-secondary">The unit joins the first of these it finds.</p>
      <p v-else class="text-body-1">No saved networks. The unit is on its hotspot whenever it is running.</p>

      <div v-if="wifi.saved.length" role="list" aria-label="Saved networks" class="mb-6">
        <div v-for="network in wifi.saved" :key="network.uuid" role="listitem" class="py-3 border-b">
          <div class="text-body-1 text-break">{{ network.name }}</div>
          <div class="d-flex flex-wrap ga-1 mt-1">
            <v-chip v-if="network.in_use" size="small" color="success" variant="tonal">Joined</v-chip>
            <v-chip v-else-if="network.in_range === true" size="small" variant="tonal">In range</v-chip>
            <v-chip v-else-if="network.in_range === false" size="small" variant="tonal">Not in range</v-chip>
            <v-chip v-if="network.could_not_join" size="small" color="warning" variant="tonal">Couldn't join</v-chip>
            <v-chip v-if="network.hidden" size="small" variant="tonal">Hidden</v-chip>
            <v-chip v-if="!network.automatic" size="small" variant="tonal">Not joined by itself</v-chip>
          </div>
          <p v-if="network.could_not_join" class="text-body-2 text-secondary mt-1">
            The unit couldn't join this network last time. It tries again by itself, after a wait that grows to an hour.
          </p>
          <div v-if="admin" class="d-flex align-center mt-1">
            <v-btn
              variant="text"
              color="error"
              size="large"
              class="ms-n4"
              :aria-label="`Forget ${network.name}`"
              :disabled="disabled"
              @click="ask(network)"
            >
              Forget
            </v-btn>
            <v-btn
              v-if="canMoveUp(network)"
              :icon="mdiArrowUp"
              variant="text"
              size="large"
              :aria-label="`Move ${network.name} up`"
              :disabled="disabled"
              @click="move(network, -1)"
            />
            <v-btn
              v-if="canMoveDown(network)"
              :icon="mdiArrowDown"
              variant="text"
              size="large"
              :aria-label="`Move ${network.name} down`"
              :disabled="disabled"
              @click="move(network, 1)"
            />
          </div>
        </div>
      </div>

      <div class="d-flex flex-wrap align-center justify-space-between mt-6 mb-1">
        <h3 class="text-subtitle-1 font-weight-medium">Nearby networks</h3>
        <v-btn
          v-if="admin"
          variant="text"
          color="primary"
          size="large"
          class="me-n4"
          :prepend-icon="mdiRefresh"
          :loading="running === 'scan'"
          :disabled="disabled"
          @click="scan"
        >
          Refresh
        </v-btn>
      </div>
      <p class="text-body-2 text-secondary mb-2">{{ age }}</p>
      <p v-if="wifi.scanned_seconds_ago !== null && !wifi.nearby.length" class="text-body-1">
        No networks were found.
      </p>

      <div v-if="wifi.nearby.length" role="list" aria-label="Nearby networks">
        <div v-for="network in wifi.nearby" :key="network.name" role="listitem" class="d-flex py-3 border-b">
          <span role="img" :aria-label="`Signal ${network.signal}%`" class="me-3">
            <v-icon :icon="signalIcon(network.signal)" />
          </span>
          <div class="flex-grow-1">
            <div class="text-body-1 text-break">
              {{ network.name }}
              <span v-if="network.security === 'password'" role="img" aria-label="Needs a password" class="ms-1">
                <v-icon :icon="mdiLock" size="small" />
              </span>
            </div>
            <div v-if="network.in_use || network.saved" class="d-flex flex-wrap ga-1 mt-1">
              <v-chip v-if="network.in_use" size="small" color="success" variant="tonal">Joined</v-chip>
              <v-chip v-else size="small" variant="tonal">Saved</v-chip>
            </div>
            <p v-if="whyNot(network.security)" class="text-body-2 text-secondary mt-1">
              {{ whyNot(network.security) }}
            </p>
          </div>
        </div>
      </div>
    </template>

    <v-alert v-if="busy" type="info" class="mt-4">{{ working }}</v-alert>
    <v-alert v-else-if="notice" :type="notice.type" class="mt-4">
      {{ notice.text }}
      <pre v-if="notice.log?.length" class="text-body-2 mt-2 text-wrap">{{ notice.log.join('\n') }}</pre>
    </v-alert>

    <ConfirmDialog
      v-model="forgetOpen"
      :title="`Forget ${target?.name ?? ''}?`"
      :text="forgetText"
      confirm-text="Forget"
      @confirm="forget"
    />
  </div>
</template>
