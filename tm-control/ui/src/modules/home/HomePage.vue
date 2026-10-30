<!--
  The home page: the device card, with the Status page's verdict as a link to it, then a tile for each app the device
  has. Viewers get only the apps everyone may use; the API leaves the admin-only ones out for them.
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, messageOf } from '../../api/client'
import type { Device, DeviceApp } from '../../api/types'
import StatusCard from '../../components/StatusCard.vue'
import { MARKS, verdict } from '../../components/status'
import { appDetails } from './apps'

const device = ref<Device | null>(null)
const error = ref('')

// The verdict from GET /status. The checks can take a few seconds, so it arrives after the card; if it can't be
// read, the card goes without it.
const health = ref<ReturnType<typeof verdict> | null>(null)

async function loadHealth() {
  try {
    const { data } = await api.GET('/api/v1/status')
    if (data) health.value = verdict(data.summary)
  } catch {
    health.value = null
  }
}

// The device's own clock, as it reports it: "2026-10-27 14:32 (UTC-04:00)"
function deviceTime(iso: string) {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2})?(Z|[+-]\d{2}:\d{2})?$/.exec(iso)
  if (!match) return iso
  const offset = !match[3] || match[3] === 'Z' ? '+00:00' : match[3]
  return `${match[1]} ${match[2]} (UTC${offset})`
}

const facts = computed(() =>
  device.value
    ? [
        { label: 'Serial number', value: device.value.serial },
        { label: 'Device time', value: deviceTime(device.value.time) },
      ]
    : [],
)

const groups = computed(() => {
  const apps = device.value?.apps ?? []
  return [
    { title: 'Apps', apps: apps.filter((app) => !app.admin_only) },
    { title: 'Device administration', apps: apps.filter((app) => app.admin_only) },
  ].filter((group) => group.apps.length > 0)
})

function tile(app: DeviceApp) {
  return { ...app, ...appDetails(app.id) }
}

async function load() {
  error.value = ''
  try {
    const { data } = await api.GET('/api/v1/system/device')
    device.value = data as Device
  } catch (caught) {
    error.value = messageOf(caught)
  }
}

onMounted(() => {
  void load()
  void loadHealth()
})
</script>

<template>
  <div>
    <h1 class="d-sr-only">Home</h1>
    <v-alert v-if="error" type="error" class="mb-6">
      {{ error }}
      <template #append>
        <v-btn variant="text" @click="load">Try again</v-btn>
      </template>
    </v-alert>
    <v-progress-linear v-else-if="!device" indeterminate color="primary" />

    <template v-if="device">
      <StatusCard :title="device.hostname" :subtitle="`Traffic Monitor ${device.tm_version}`" :items="facts">
        <div v-if="health" class="d-flex align-center ga-2 mt-4">
          <v-icon :icon="MARKS[health.status].icon" :color="MARKS[health.status].color" />
          <router-link to="/status" class="text-body-1 text-primary">{{ health.text }}</router-link>
        </div>
      </StatusCard>

      <section v-for="group in groups" :key="group.title" class="mt-10">
        <h2 class="text-h6 mb-4">{{ group.title }}</h2>
        <v-row>
          <v-col v-for="app in group.apps.map(tile)" :key="app.id" cols="12" sm="6">
            <v-card :href="app.path" variant="outlined" rounded="lg" height="100%">
              <v-card-item>
                <template #prepend>
                  <v-icon :icon="app.icon" color="primary" size="28" />
                </template>
                <v-card-title class="text-subtitle-1 font-weight-medium">{{ app.title }}</v-card-title>
              </v-card-item>
              <v-card-text v-if="app.description" class="text-body-2 text-secondary pt-0">
                {{ app.description }}
              </v-card-text>
            </v-card>
          </v-col>
        </v-row>
      </section>

      <p v-if="groups.length === 0" class="text-body-1 mt-10">
        No apps are installed on this device yet. Run the installer to add them.
      </p>
    </template>
  </div>
</template>
