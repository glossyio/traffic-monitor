<!--
  The Network page (GET /network), for everyone signed in: this device's names, its Ethernet and Wi-Fi links with
  their hardware and IP addresses, the internet, and the hotspot. Every name and address has a Copy button. The
  hotspot is read-only for a viewer; an admin gets its settings (HotspotSettings). The hotspot's password is never
  part of this answer.
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import { useSession } from '../../stores/session'
import FactRow from './FactRow.vue'
import HotspotSettings from './HotspotSettings.vue'
import { internetLine, wifiLine } from './summary'

type NetworkState = components['schemas']['NetworkState']
type Link = components['schemas']['Link']

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

async function load() {
  loadError.value = ''
  try {
    const { data } = await api.GET('/api/v1/network')
    state.value = data as NetworkState
  } catch (error) {
    loadError.value = messageOf(error)
  }
}

onMounted(load)

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
        <v-btn variant="text" @click="load">Try again</v-btn>
      </template>
    </v-alert>
    <v-progress-linear v-else-if="!state" indeterminate color="primary" />

    <template v-if="state">
      <v-alert v-if="!state.readable" type="warning" class="mb-6">
        The network state couldn't be read, because the network service didn't answer. The names below are still right.
        <template #append>
          <v-btn variant="text" @click="load">Try again</v-btn>
        </template>
      </v-alert>

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
        <h2 class="text-h6 mb-4">Hotspot</h2>
        <p v-if="!state.hotspot" class="text-body-1">The hotspot isn't set up on this unit.</p>
        <HotspotSettings
          v-else-if="session.isAdmin"
          :hotspot="state.hotspot"
          :local-name="state.local_name"
          :on-hotspot="!!session.status?.hotspot"
          @changed="load"
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
  </div>
</template>
