<!--
  The Wi-Fi join, as the Network page shows it above "This device" for as long as the unit has one to show: the test,
  the countdown to the switch, and the result until an admin dismisses it. The page is often open on a phone that is
  on the unit's own hotspot, which goes away for the test, so each stage says what to do next as well as what
  happened, and a page that has lost the unit (`lost`) says that is expected rather than showing an error. The times
  come from the device (the page counts the seconds between its answers, see `useJoin`). An admin gets Switch now and
  Cancel during the countdown and Dismiss on a result; a viewer sees the same words and no buttons but Copy, which
  changes nothing. The addresses are plain text: inside a phone's sign-in window a link would open in that window.
  Emits `changed` after a button was pressed, so the page asks again.
-->
<script setup lang="ts">
import {
  mdiAlertCircle,
  mdiCheckCircle,
  mdiCloseCircle,
  mdiTimerSand,
  mdiWifiAlert,
  mdiWifiCheck,
  mdiWifiSync,
} from '@mdi/js'
import { computed, ref, watch } from 'vue'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import CopyButton from '../../components/CopyButton.vue'
import { HOTSPOT_PROFILE, clock } from './join'

type JoinState = components['schemas']['JoinState']
type HotspotState = components['schemas']['HotspotState']
type Stage = JoinState['stage']

const props = defineProps<{
  join: JoinState
  lost: boolean
  localName: string
  mac: string | null
  hotspot: HotspotState | null
  admin: boolean
}>()
const emit = defineEmits<{ changed: [] }>()

const name = computed(() => props.join.network)

// Switch now ends the countdown at once, but the device only says so on its next answer, and a page on the hotspot
// may never get that answer. Until the stage moves on, the card already says the unit is joining.
const switched = ref(false)
watch(
  () => props.join.stage,
  (stage) => {
    if (stage !== 'countdown') switched.value = false
  },
)
const stage = computed<Stage>(() => (props.join.stage === 'countdown' && switched.value ? 'switching' : props.join.stage))

// Shape carries the stage as well as color
const MARKS: Record<Stage, { icon: string; color: string; label: string }> = {
  testing: { icon: mdiWifiSync, color: 'primary', label: 'Testing' },
  countdown: { icon: mdiWifiCheck, color: 'success', label: 'Test passed' },
  switching: { icon: mdiTimerSand, color: 'primary', label: 'Joining' },
  joined: { icon: mdiCheckCircle, color: 'success', label: 'Joined' },
  failed: { icon: mdiCloseCircle, color: 'error', label: 'Failed' },
  cancelled: { icon: mdiWifiAlert, color: 'secondary', label: 'Cancelled' },
  switch_failed: { icon: mdiAlertCircle, color: 'warning', label: 'Not joined' },
  interrupted: { icon: mdiAlertCircle, color: 'warning', label: 'Interrupted' },
}
const mark = computed(() => MARKS[stage.value])

const wasOnHotspot = computed(() => props.join.before === HOTSPOT_PROFILE)

const lostText = computed(
  () =>
    `This page lost the unit, which is expected during the test. When ${props.hotspot?.name ?? 'the hotspot'} reappears, join it again. This page then shows the result.`,
)

const addresses = computed(() => {
  const local = `http://${props.localName}/`
  return props.join.address ? `${local} or http://${props.join.address}/` : local
})

const internet = computed(() => {
  switch (props.join.internet) {
    case 'reachable':
      return 'Internet: reachable'
    case 'not_reachable':
      return 'Internet: not reachable'
    case 'sign_in_page':
      return 'Joined, but this network needs a sign-in page, so the unit has no internet there.'
    default:
      return ''
  }
})

// The sentence, in two pieces with the MAC address (and its Copy button) between them when the unit knows it
const notJoinedHead = computed(
  () =>
    `The unit couldn't join ${name.value}. The usual cause is a wrong password. If the network only admits listed devices, add the unit's Wi-Fi MAC address${props.mac ? ', ' : ' '}`,
)
const notJoinedTail = computed(() => `${props.mac ? ' ' : ''}to its list. ${kept.value}`)
const notJoined = computed(() => stage.value === 'failed' && props.join.reason === 'not_joined')

const kept = computed(() => (props.join.saved ? 'The saved network is kept.' : 'Nothing was saved.'))

// The one paragraph for every stage that has just a sentence or two to say
const text = computed(() => {
  const n = name.value
  switch (stage.value) {
    case 'testing':
      return `Testing ${n}. This takes up to a minute.`
    case 'switching':
      return `The unit is joining ${n} now. Join ${n} yourself, then open ${addresses.value}.`
    case 'joined':
      return props.join.address
        ? `The unit is on ${n}. Its address there is ${props.join.address}.`
        : `The unit is on ${n}.`
    case 'cancelled':
      return `Cancelled. The unit didn't join ${n}.`
    case 'switch_failed':
      return `The test passed, but the unit couldn't join ${n} when the countdown ended. It is back where it was. ${n} stays saved, and the unit tries it again by itself.`
    case 'interrupted':
      return `The test of ${n} was interrupted. The unit goes back to where it was within a minute and a half.`
    case 'failed':
      switch (props.join.reason) {
        case 'not_in_range':
          return `${n} isn't in range right now, so nothing was tried.`
        case 'not_joined':
          return '' // written in the template, where the MAC address has its Copy button
        case 'no_address':
          return `${n} let the unit in but gave it no address. ${kept.value}`
        case 'busy':
          return 'The unit was busy with its Wi-Fi. Try again in a minute.'
        default:
          return "The test couldn't run. The unit is back where it was."
      }
    default:
      return ''
  }
})

const acting = ref(false)
const problem = ref('')

// Each button is a POST with an empty JSON body (the API's cross-site check wants one), then the page asks again
async function press(path: '/api/v1/network/wifi/join/switch' | '/api/v1/network/wifi/join/cancel') {
  if (acting.value) return
  acting.value = true
  problem.value = ''
  try {
    await api.POST(path, { body: {} as never })
    if (path.endsWith('/switch')) switched.value = true
  } catch (error) {
    problem.value = messageOf(error)
  } finally {
    acting.value = false
    emit('changed') // a refusal means the card is out of date
  }
}

const finished = computed(() => ['joined', 'failed', 'cancelled', 'switch_failed', 'interrupted'].includes(stage.value))
</script>

<template>
  <v-card variant="outlined" rounded="lg" class="mb-8">
    <v-card-text class="text-body-1 text-break">
      <template v-if="stage === 'countdown'">
        <div class="d-flex align-center ga-3 mb-3">
          <span role="img" :aria-label="mark.label"><v-icon :icon="mark.icon" :color="mark.color" size="28" /></span>
          <h2 class="text-h6">{{ name }} works</h2>
        </div>
        <div v-if="join.address" class="mb-2">
          The unit's address there:
          <span class="text-no-wrap">{{ join.address }}<CopyButton :text="join.address" :label="`the unit's address on ${name}`" /></span>
        </div>
        <div v-if="mac" class="mb-2">Wi-Fi MAC address: {{ mac }}</div>
        <div class="mb-2">Or open: http://{{ localName }}/</div>
        <div v-if="internet" class="mb-3">{{ internet }}</div>
        <p class="text-h6 mb-3">Joining {{ name }} in {{ clock(join.seconds_left ?? 0) }}</p>
        <div v-if="admin" class="d-flex ga-2 mb-3">
          <v-btn variant="outlined" size="large" :disabled="acting" @click="press('/api/v1/network/wifi/join/cancel')">
            Cancel
          </v-btn>
          <v-btn
            color="primary"
            variant="flat"
            size="large"
            :disabled="acting"
            @click="press('/api/v1/network/wifi/join/switch')"
          >
            Switch now
          </v-btn>
        </div>
        <p>
          <template v-if="wasOnHotspot">When the unit joins {{ name }}, its hotspot stops. </template>Join
          {{ name }} with your phone or computer too, then open one of the addresses above.
        </p>
      </template>

      <div v-else class="d-flex ga-3">
        <span role="img" :aria-label="mark.label"><v-icon :icon="mark.icon" :color="mark.color" size="28" /></span>
        <div class="flex-grow-1">
          <p v-if="notJoined">
            {{ notJoinedHead }}<span v-if="mac" class="text-no-wrap">{{ mac }},<span class="d-inline-flex my-n3 align-middle"><CopyButton :text="mac" label="Wi-Fi MAC address" /></span></span>{{ notJoinedTail }}
          </p>
          <p v-else>{{ text }}</p>
          <v-progress-linear v-if="stage === 'testing'" indeterminate color="primary" class="mt-3" />
          <p v-if="stage === 'testing' && lost" class="mt-3">{{ lostText }}</p>
          <v-btn
            v-if="admin && finished"
            variant="text"
            color="primary"
            size="large"
            class="ms-n4 mt-1"
            :disabled="acting"
            @click="press('/api/v1/network/wifi/join/cancel')"
          >
            Dismiss
          </v-btn>
        </div>
      </div>

      <v-alert v-if="problem" type="error" class="mt-3">{{ problem }}</v-alert>
    </v-card-text>
  </v-card>
</template>
