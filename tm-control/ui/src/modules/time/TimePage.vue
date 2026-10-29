<!--
  The Date and time page (GET /time): the device's clock beside this browser's, both ticking, and the difference in
  words. Admins set the device's time and time zone from this browser, pick a time zone from the device's list
  (GET /time/timezones), and turn NTP on or off, each with POST /time. Viewers see the clocks, the time zone, and
  whether the device keeps time from the internet.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import type { Note } from '../../components/status'
import { useSession } from '../../stores/session'
import { TOLERANCE_S, browserOffset, comparison, parseDeviceTime, wallClock } from './clock'

type TimeState = components['schemas']['TimeState']
type TimeResult = components['schemas']['TimeResult']

const RESTARTING = 'Frigate and Node-RED are restarting.'

const session = useSession()
const state = ref<TimeState | null>(null)
const loadError = ref('')
const zone = ref('') // the time zone picker's choice; each answer from the device resets it to the device's zone

// The device's clock as of its last answer: the instant it reported, when (on this browser's clock) the answer
// came, and its offset from UTC. Its clock on the page ticks on from there.
const device = ref<{ instant: number; at: number; offset: number } | null>(null)
const now = ref(Date.now())
let tick: ReturnType<typeof setInterval> | undefined

function show(next: TimeState) {
  state.value = next
  const parsed = parseDeviceTime(next.device_time)
  device.value = parsed ? { ...parsed, at: Date.now() } : null
  zone.value = next.timezone
}

async function load() {
  loadError.value = ''
  try {
    const { data } = await api.GET('/api/v1/time')
    show(data as TimeState)
  } catch (error) {
    loadError.value = messageOf(error)
  }
}

const clocks = computed(() => {
  const browser = { label: 'This browser', ...wallClock(now.value, browserOffset(now.value)) }
  if (!device.value) return [{ label: 'This device', time: 'Unknown', date: '', zone: '' }, browser]
  const deviceNow = device.value.instant + (now.value - device.value.at)
  return [{ label: 'This device', ...wallClock(deviceNow, device.value.offset) }, browser]
})

// How far the device's clock is from this browser's, in seconds, and whether they show the same offset
const difference = computed(() => {
  if (!device.value) return null
  return {
    seconds: (device.value.instant - device.value.at) / 1000,
    sameZone: device.value.offset === browserOffset(now.value),
  }
})
const agree = computed(
  () => !!difference.value && Math.abs(difference.value.seconds) <= TOLERANCE_S && difference.value.sameZone,
)

// "Set from this browser": the browser's instant and time zone. The device keeps NTP's time if NTP has it, and
// skips a time zone it doesn't know.
const setting = ref(false)

// What the last change said, under the control that made it. Each change clears the earlier results, which it may
// have made untrue ("already keeps time from the internet" once NTP is off).
const setResult = ref<Note | null>(null)
const zoneResult = ref<Note | null>(null)
const ntpError = ref('')

function clearResults() {
  setResult.value = null
  zoneResult.value = null
  ntpError.value = ''
}

function setOutcome(result: TimeResult, timezone: string) {
  const restarting = result.restarting.length > 0 // only a time zone change restarts anything
  let text = 'Time set from this browser.'
  if (result.timezone_unknown) {
    // A browser's time zone list can be newer than the device's: the time went on, the zone is left for the picker
    if (result.time_kept_from_ntp) text = "The device already keeps time from the internet, so its time didn't change."
    return `${text} The device doesn't know this browser's time zone (${timezone}), so pick one below.`
  }
  if (result.ntp_left_off) {
    // The device's clock was ahead: turning internet time back on would have put that time back
    text +=
      " Internet time is now off, because turning it back on put the device's own, wrong time back. Turn on Keep " +
      'time from the internet once the device is online.'
  }
  if (result.time_kept_from_ntp) {
    text = restarting
      ? 'The device already keeps time from the internet, so only the time zone changed.'
      : "The device already keeps time from the internet and uses this browser's time zone, so nothing changed."
  }
  return restarting ? `${text} ${RESTARTING}` : text
}

async function setFromBrowser() {
  setting.value = true
  clearResults()
  try {
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone
    const { data } = await api.POST('/api/v1/time', { body: { time: new Date().toISOString(), timezone } })
    const result = data as TimeResult
    show(result)
    setResult.value = { text: setOutcome(result, timezone), error: false }
  } catch (error) {
    setResult.value = { text: messageOf(error), error: true }
  } finally {
    setting.value = false
  }
}

// The time zone picker, over the zones the device knows. When it gets focus, its text is selected, so typing
// "Berlin" replaces the current zone instead of landing in the middle of it (where a tap puts the caret).
function selectZoneText(event: FocusEvent) {
  const input = event.target
  if (input instanceof HTMLInputElement) void nextTick(() => input.select()) // after Vuetify writes the zone in
}

const timezones = ref<string[]>([])
const savingZone = ref(false)

async function loadZones() {
  try {
    const { data } = await api.GET('/api/v1/time/timezones')
    timezones.value = data as string[]
  } catch (error) {
    zoneResult.value = { text: messageOf(error), error: true }
  }
}

async function saveZone() {
  savingZone.value = true
  clearResults()
  try {
    const { data } = await api.POST('/api/v1/time', { body: { timezone: zone.value } })
    const result = data as TimeResult
    show(result)
    const restarting = result.restarting.length > 0
    zoneResult.value = { text: restarting ? `Time zone saved. ${RESTARTING}` : 'Time zone saved.', error: false }
  } catch (error) {
    zoneResult.value = { text: messageOf(error), error: true }
  } finally {
    savingZone.value = false
  }
}

// NTP: keeping time from the internet
const ntpBusy = ref(false)

const ntpSentence = computed(() => {
  const ntp = state.value?.ntp
  if (!ntp) return ''
  if (!ntp.enabled && !ntp.available) return 'The device has no way to keep time from the internet, so its clock runs on its own.'
  if (!ntp.enabled) return "The device doesn't check the time on the internet, so its clock runs on its own."
  if (ntp.synchronized) return 'The device keeps time from the internet.'
  return 'The device has no time source right now, so its clock runs on its own.'
})

async function setNtp(on: boolean | null) {
  ntpBusy.value = true
  clearResults()
  try {
    const { data } = await api.POST('/api/v1/time', { body: { ntp: !!on } })
    show(data as TimeResult)
  } catch (error) {
    ntpError.value = messageOf(error)
  } finally {
    ntpBusy.value = false
  }
}

onMounted(() => {
  void load()
  if (session.isAdmin) void loadZones()
  tick = setInterval(() => (now.value = Date.now()), 1000)
})

onBeforeUnmount(() => clearInterval(tick))
</script>

<template>
  <div>
    <h1 class="text-h5 text-primary mb-6">Date and time</h1>

    <v-alert v-if="loadError" type="error" class="mb-6">
      {{ loadError }}
      <template #append>
        <v-btn variant="text" @click="load">Try again</v-btn>
      </template>
    </v-alert>
    <v-progress-linear v-else-if="!state" indeterminate color="primary" />

    <template v-if="state">
      <!-- Side by side from 600 px; on a phone the device's clock comes first -->
      <v-row>
        <v-col v-for="clock in clocks" :key="clock.label" cols="12" sm="6">
          <div class="text-body-2 text-secondary">{{ clock.label }}</div>
          <div class="text-h4 clock">{{ clock.time }}</div>
          <div class="text-body-1">{{ clock.date }}</div>
          <div class="text-body-2 text-secondary">{{ clock.zone }}</div>
        </v-col>
      </v-row>
      <p v-if="difference" class="text-body-1 mt-4">{{ comparison(difference.seconds, difference.sameZone) }}</p>

      <template v-if="session.isAdmin">
        <!-- Filled when the clocks differ, so the fix is the page's main button; outlined when there's nothing to fix -->
        <v-btn
          :variant="agree ? 'outlined' : 'flat'"
          color="primary"
          size="large"
          class="mt-4"
          :loading="setting"
          @click="setFromBrowser"
        >
          Set from this browser
        </v-btn>
        <v-alert v-if="setResult?.error" type="error" class="mt-4">{{ setResult.text }}</v-alert>
        <p v-else-if="setResult" class="text-body-1 mt-4">{{ setResult.text }}</p>
      </template>

      <!-- No heading: the picker's own label says "Time zone", and a heading above it would say it twice -->
      <section class="mt-10">
        <template v-if="session.isAdmin">
          <v-autocomplete
            v-model="zone"
            :items="timezones"
            label="Time zone"
            variant="outlined"
            color="primary"
            hide-details
            class="mb-4"
            @focusin="selectZoneText"
          />
          <v-btn
            color="primary"
            variant="outlined"
            size="large"
            :loading="savingZone"
            :disabled="!zone || zone === state.timezone"
            @click="saveZone"
          >
            Save time zone
          </v-btn>
          <v-alert v-if="zoneResult?.error" type="error" class="mt-4">{{ zoneResult.text }}</v-alert>
          <p v-else-if="zoneResult" class="text-body-1 mt-4">{{ zoneResult.text }}</p>
        </template>
        <template v-else>
          <div class="text-body-2 text-secondary">Time zone</div>
          <div class="text-body-1">{{ state.timezone }}</div>
        </template>
      </section>

      <section class="mt-10">
        <template v-if="session.isAdmin">
          <v-switch
            :model-value="state.ntp.enabled"
            label="Keep time from the internet"
            color="primary"
            hide-details
            :loading="ntpBusy"
            :disabled="ntpBusy || (!state.ntp.enabled && !state.ntp.available)"
            @update:model-value="setNtp"
          />
          <p class="text-body-2 text-secondary">{{ ntpSentence }}</p>
          <v-alert v-if="ntpError" type="error" class="mt-4">{{ ntpError }}</v-alert>
        </template>
        <p v-else class="text-body-1">{{ ntpSentence }}</p>
      </section>

      <p v-if="!session.isAdmin" class="text-body-1 text-secondary mt-10">
        An administrator can set the time and time zone here.
      </p>
    </template>
  </div>
</template>

<style scoped>
/* The clocks' digits all take the same width, so the time doesn't shift sideways as it ticks */
.clock {
  font-variant-numeric: tabular-nums;
}
</style>
