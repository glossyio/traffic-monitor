<!--
  The Network page (GET /network), for everyone signed in: this device's names, its Ethernet and Wi-Fi links with
  their hardware and IP addresses, the internet, the saved and nearby Wi-Fi networks (WifiNetworks, from its own
  answer, GET /network/wifi), and the hotspot. Every name and address has a Copy button. The networks and the hotspot
  are read-only for a viewer; an admin gets their controls. The hotspot's password is never part of this answer.

  A Wi-Fi join (GET /network/join, kept by useJoin) has its card above "This device" for as long as the unit has one to
  show. While one is pending, and while either section runs a job of its own, both sections are locked. The page owns
  the Join dialog and sends the request, because it is also what follows the join: after a request is accepted, the
  card says the unit is testing until the unit reports the join itself, and says so if it never does.
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import { useSession } from '../../stores/session'
import FactRow from './FactRow.vue'
import HotspotSettings from './HotspotSettings.vue'
import JoinCard from './JoinCard.vue'
import JoinDialog from './JoinDialog.vue'
import WifiNetworks from './WifiNetworks.vue'
import { HOTSPOT_PROFILE, JOIN_POLL_MS, type JoinState, pending, useJoin } from './join'
import { internetLine, wifiLine } from './summary'

type NetworkState = components['schemas']['NetworkState']
type Link = components['schemas']['Link']
type Wifi = components['schemas']['WifiNetworks']
type Nearby = components['schemas']['Nearby']

interface Fact {
  label: string
  value: string
  copy?: string // what the Copy button copies, if there is one: "Copy <this>"
}

interface Block extends Fact {
  details: Fact[]
}

const session = useSession()
const state = ref<NetworkState | null>(null)
const loadError = ref('')

// Each load counts itself, so the answer of one that a newer load has overtaken (a request that hung while the unit
// went away and failed much later) is dropped, whether it worked or not. A quiet load keeps what the page has when it
// fails and says nothing: it is the page asking again on its own, not the person, and the join card says what is going on.
let loads = 0
async function load(quiet = false) {
  const mine = ++loads
  if (!quiet) loadError.value = ''
  try {
    const { data } = await api.GET('/api/v1/network')
    if (mine !== loads) return
    state.value = data as NetworkState
    loadError.value = ''
  } catch (error) {
    if (mine !== loads || quiet) return
    loadError.value = messageOf(error)
  }
}

// The saved and nearby Wi-Fi networks. A failure here shows in its own section; it never hides the rest of the page.
const wifi = ref<Wifi | null>(null)
const wifiError = ref('')

let wifiLoads = 0
async function loadWifi(quiet = false) {
  const mine = ++wifiLoads
  if (!quiet) wifiError.value = ''
  try {
    const { data } = await api.GET('/api/v1/network/wifi')
    if (mine !== wifiLoads) return
    wifi.value = data as Wifi
    wifiError.value = ''
  } catch (error) {
    if (mine !== wifiLoads || quiet) return
    wifiError.value = messageOf(error)
  }
}

const loadAll = () => Promise.all([load(), loadWifi()])
const loadQuietly = () => Promise.all([load(true), loadWifi(true)])

// The join, and the lock it puts on the sections. `running` is what each section says about a job it started.
const { join, lost, refresh: refreshJoin, stop: stopJoin } = useJoin()
const running = reactive({ wifi: false, hotspot: false })

// A join the page has just asked for, until the unit reports it. The device may still say the join before it (a
// result nobody dismissed) for a moment, so a join counts as the new one when it differs from that.
const START_WAIT_MS = 15_000
const starting = ref<{ name: string; saved: boolean; stale: string } | null>(null)
const joinNotice = ref<{ type: 'warning' | 'error'; text: string } | null>(null)
let startedAt = 0
let startTick: ReturnType<typeof setInterval> | undefined
let startLimit: ReturnType<typeof setTimeout> | undefined

const keyOf = (state: JoinState | null) => (state ? `${state.stage}|${state.network}|${state.finished_at}` : '')
const reported = computed(() => !!join.value && (!starting.value || keyOf(join.value) !== starting.value.stale))

const shown = computed<JoinState | null>(() => {
  if (!starting.value || reported.value) return join.value
  return {
    stage: 'testing',
    network: starting.value.name,
    saved: starting.value.saved,
    before: state.value?.wifi?.mode === 'hotspot' ? HOTSPOT_PROFILE : null,
    joined: null,
    reason: null,
    address: null,
    internet: null,
    seconds_left: null,
    finished_at: null,
  }
})
const joinPending = computed(() => pending(shown.value))
const jobRunning = computed(() => running.wifi || running.hotspot)
const locked = computed(() => joinPending.value || jobRunning.value)
const lockedByJob = computed(() => jobRunning.value && !joinPending.value)

function endStart() {
  clearInterval(startTick)
  clearTimeout(startLimit)
  starting.value = null
}

// Asks the device whether the join began; gives up when it says there is none and the page can reach it, which
// is not the case while the test itself has taken the unit away
async function checkStart() {
  await refreshJoin()
  if (!starting.value) return
  if (reported.value) endStart()
  else if (Date.now() - startedAt >= START_WAIT_MS && !lost.value) {
    endStart()
    joinNotice.value = { type: 'warning', text: "The test didn't start. Try again." }
  }
}

function begin(network: Nearby) {
  endStart()
  startedAt = Date.now()
  starting.value = { name: network.name, saved: network.saved, stale: keyOf(join.value) }
  startTick = setInterval(() => void checkStart(), JOIN_POLL_MS)
  startLimit = setTimeout(() => void checkStart(), START_WAIT_MS)
}

const joinTarget = ref<Nearby | null>(null)
const joinOpen = ref(false)

function ask(network: Nearby) {
  joinTarget.value = network
  joinOpen.value = true
}

// The password is typed in the dialog, which sends nothing itself; null uses the saved one
async function startJoin(password: string | null) {
  const network = joinTarget.value
  if (!network) return
  joinNotice.value = null
  try {
    await api.POST('/api/v1/network/wifi/join', { body: { name: network.name, password } })
    begin(network)
  } catch (error) {
    joinNotice.value = { type: 'error', text: messageOf(error) }
    void loadAll() // a refusal usually means the page's list is out of date
  }
}

let stopWatching = () => {}
onMounted(async () => {
  await Promise.all([loadAll(), refreshJoin()])
  // Once the first answers are in, a change of stage means the unit's network or hotspot may have changed, except
  // on the way into the test, when nothing has yet. The reload is quiet: right after a test the link may still be flaky.
  stopWatching = watch(
    () => join.value?.stage,
    (stage) => {
      if (stage !== 'testing') void loadQuietly()
    },
  )
})
onBeforeUnmount(() => {
  stopWatching()
  stopJoin()
  endStart()
})

// A link's hardware address, addresses, gateway, and DNS servers, each with its Copy button
function details(name: string, link: Link): Fact[] {
  const facts: Fact[] = []
  if (link.mac) facts.push({ label: 'MAC address', value: link.mac, copy: `${name} MAC address` })
  for (const address of link.addresses) facts.push({ label: 'IP address', value: address, copy: `${name} IP address` })
  if (link.gateway) facts.push({ label: 'Gateway', value: link.gateway, copy: `${name} gateway` })
  for (const server of link.dns) facts.push({ label: 'DNS server', value: server, copy: `${name} DNS server` })
  return facts
}

const names = computed<Fact[]>(() =>
  state.value
    ? [
        { label: 'Name', value: state.value.hostname, copy: 'name' },
        { label: 'Local name', value: state.value.local_name, copy: 'local name' },
      ]
    : [],
)

// What the unit is connected to. When NetworkManager didn't answer, "no Ethernet" and "no radio" would only mean
// "none found", so nothing past the names is shown.
const blocks = computed<Block[]>(() => {
  const current = state.value
  if (!current?.readable) return []
  const found: Block[] = []
  const { ethernet, wifi, hotspot } = current
  if (ethernet) {
    found.push({
      label: 'Ethernet',
      value: ethernet.connected ? 'Connected' : 'Not connected',
      details: details('Ethernet', ethernet),
    })
  }
  found.push(
    wifi
      ? { label: 'Wi-Fi', value: wifiLine(wifi, hotspot), details: details('Wi-Fi', wifi) }
      : { label: 'Wi-Fi', value: 'No built-in Wi-Fi radio', details: [] },
  )
  found.push({ label: 'Internet', value: internetLine(current.internet), details: [] })
  return found
})

const hotspotFacts = computed<Fact[]>(() => {
  const hotspot = state.value?.hotspot
  if (!hotspot) return []
  return [
    { label: 'State', value: hotspot.enabled ? 'On' : 'Off' },
    { label: 'Name', value: hotspot.name, copy: 'hotspot name' },
    { label: 'Name hidden', value: hotspot.hidden ? 'Yes' : 'No' },
  ]
})
</script>

<template>
  <div>
    <h1 class="text-h5 text-primary mb-6">Network</h1>

    <v-alert v-if="loadError" type="error" class="mb-6">
      {{ loadError }}
      <template #append>
        <v-btn variant="text" @click="loadAll">Try again</v-btn>
      </template>
    </v-alert>
    <v-progress-linear v-else-if="!state" indeterminate color="primary" />

    <template v-if="state">
      <v-alert v-if="!state.readable" type="warning" class="mb-6">
        The network state couldn't be read, because the network service didn't answer. The names below are still right.
        <template #append>
          <v-btn variant="text" @click="loadAll">Try again</v-btn>
        </template>
      </v-alert>

      <JoinCard
        v-if="shown"
        :join="shown"
        :lost="lost"
        :local-name="state.local_name"
        :mac="state.wifi?.mac ?? null"
        :hotspot="state.hotspot"
        :admin="session.isAdmin"
        @changed="refreshJoin"
      />

      <section>
        <h2 class="text-h6 mb-4">This device</h2>
        <FactRow v-for="fact in names" :key="fact.label" v-bind="fact" class="mb-4" />

        <div v-for="block in blocks" :key="block.label" class="mb-4">
          <FactRow :label="block.label" :value="block.value" />
          <div v-if="block.details.length" class="border-s-md ps-3 mt-2">
            <FactRow
              v-for="(fact, index) in block.details"
              :key="`${fact.label}${index}`"
              v-bind="fact"
              class="mb-2"
            />
          </div>
        </div>
      </section>

      <section v-if="state.readable" class="mt-10">
        <h2 class="text-h6 mb-4">Wi-Fi networks</h2>
        <v-alert v-if="wifiError" type="error">
          {{ wifiError }}
          <template #append>
            <v-btn variant="text" @click="loadWifi()">Try again</v-btn>
          </template>
        </v-alert>
        <v-progress-linear v-else-if="!wifi" indeterminate color="primary" />
        <WifiNetworks
          v-else
          :wifi="wifi"
          :hotspot="state.hotspot"
          :admin="session.isAdmin"
          :locked="locked"
          :locked-by-job="lockedByJob"
          @changed="loadAll"
          @join="ask"
          @busy="(on: boolean) => (running.wifi = on)"
        />
        <v-alert v-if="joinNotice" :type="joinNotice.type" class="mt-4">{{ joinNotice.text }}</v-alert>
      </section>

      <section v-if="state.readable" class="mt-10">
        <h2 class="text-h6 mb-4">Hotspot</h2>
        <p v-if="!state.hotspot" class="text-body-1">The hotspot isn't set up on this unit.</p>
        <HotspotSettings
          v-else-if="session.isAdmin"
          :hotspot="state.hotspot"
          :local-name="state.local_name"
          :on-hotspot="!!session.status?.hotspot"
          :locked="locked"
          :locked-by-job="lockedByJob"
          @changed="loadAll"
          @busy="(on: boolean) => (running.hotspot = on)"
        />
        <template v-else>
          <FactRow v-for="fact in hotspotFacts" :key="fact.label" v-bind="fact" class="mb-4" />
          <div class="mb-4">
            <div class="text-body-2 text-secondary">Address</div>
            <div class="text-body-1 text-break">http://{{ state.hotspot.address }}/</div>
            <div class="text-body-1 text-break">http://{{ state.local_name }}/</div>
          </div>
          <p class="text-body-2 text-secondary">An administrator can change the hotspot here.</p>
        </template>
      </section>
    </template>

    <JoinDialog
      v-if="joinTarget && state?.wifi"
      v-model="joinOpen"
      :network="joinTarget"
      :mac="state.wifi.mac"
      :wifi="state.wifi"
      :hotspot="state.hotspot"
      :on-hotspot="!!session.status?.hotspot"
      @join="startJoin"
    />
  </div>
</template>
