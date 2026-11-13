<!--
  The hotspot's settings, for an admin: turn it on or off, rename it, show / change / set its password, hide its name.
  Each change is POST /network/hotspot, which starts a root job that restarts the hotspot, and the page follows the
  job. The restart often disconnects the very phone the admin is using (when it is on the hotspot, `onHotspot`), so
  every warning says so before the change, and a request that fails while the job runs is not an error here: it is
  the page losing the unit, and the page says how to get back. One change at a time: every control is disabled while
  a job runs. The password is fetched from the device each time Show is tapped and dropped on Hide, never kept.
  While `locked` (a Wi-Fi join is pending, or the Wi-Fi networks section runs a job) every control is disabled and
  the page says why. Emits `busy` when a job it started begins and ends, and `changed` once a job has finished, so the
  page can load the state again.
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ApiError, api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import type { Job } from '../../api/types'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { followJob } from '../../components/jobs'
import FactRow from './FactRow.vue'
import HotspotField from './HotspotField.vue'
import { nameRule, passwordRule } from './rules'

type HotspotState = components['schemas']['HotspotState']
type HotspotChange = components['schemas']['HotspotChange']

const props = defineProps<{
  hotspot: HotspotState
  localName: string
  onHotspot: boolean
  locked: boolean // a join is pending or another section runs a job: nothing here may change
  lockedByJob?: boolean // ...and it is only another section's job, not the join
}>()
const emit = defineEmits<{ changed: []; busy: [running: boolean]; notice: [notice: Notice | null] }>()

// The words for the warnings. The turn-off and hiding sentences are the design's.
const RESTART = 'The hotspot restarts, and phones on it are disconnected. Each phone must rejoin by hand.'
const WRITE_DOWN = 'Write the new password down before you save. Every phone needs it to rejoin.'
const TURN_OFF =
  'With the hotspot off, this unit has no wireless way in when its Wi-Fi network is missing. You would need an Ethernet cable.'
const HIDING = 'The hotspot is still on and can still be found by scanning. Only its name is hidden.'
const ANDROID = 'On Android, add the network by hand and tick Hidden network, or the phone never connects.'
const ON_IT = "You're on the hotspot now, so this page stops answering when you save."

const join = (...parts: (string | false)[]) => parts.filter(Boolean).join(' ')
const lines = (...parts: (string | false)[]) => parts.filter(Boolean).join('\n') // paragraphs, in a dialog

// A change that restarts the hotspot warns only when the hotspot is up; when this page came over the hotspot, it
// also says the page stops answering
const restart = computed(() => props.hotspot.active && join(RESTART, props.onHotspot && ON_IT))
const nameWarning = computed(() => restart.value || '')
const hasPassword = computed(() => props.hotspot.security !== 'none')
const passwordWarning = computed(() => (restart.value ? `${WRITE_DOWN}\n${restart.value}` : WRITE_DOWN))

type Kind = 'name' | 'password' | 'hidden' | 'on' | 'off'
const running = ref<Kind | null>(null)
const busy = computed(() => running.value !== null)
const disabled = computed(() => busy.value || props.locked)
watch(busy, (running) => emit('busy', running))

export interface Notice {
  type: 'success' | 'info' | 'warning' | 'error'
  text: string
  log?: string[]
}
const notice = ref<Notice | null>(null)
watch(notice, (now) => emit('notice', now)) // so the page can open this section when there is something to read

// The password, only while it is shown: undefined while hidden, '' when the device has none
const revealed = ref<string | undefined>(undefined)
const asking = ref(false)
// Counts the times the password was dropped, so a Show that was still asking when it was dropped is discarded
let shown = 0
function forget() {
  shown += 1
  revealed.value = undefined
}
watch(() => props.hotspot, forget) // a new state may mean a new password

async function show() {
  asking.value = true
  notice.value = null
  const mine = shown
  try {
    const { data } = await api.GET('/api/v1/network/hotspot/password')
    if (mine === shown) revealed.value = (data as components['schemas']['HotspotPassword']).password ?? ''
  } catch (error) {
    if (mine === shown) notice.value = { type: 'error', text: messageOf(error) }
  } finally {
    asking.value = false
  }
}

let left = false
let following: ReturnType<typeof followJob> | null = null
onBeforeUnmount(() => {
  left = true
  following?.cancel()
})

const saved = (job: Job) => job.log.some((line) => line.endsWith('the settings are saved'))
const nothingToChange = (job: Job) => job.log.some((line) => line.endsWith('nothing to change'))

// What the page says when it loses the unit while the job runs
function lostText(kind: Kind, name: string): string {
  if (kind === 'off') return 'The hotspot is off. Reach the unit on its Wi-Fi network or by Ethernet.'
  if (kind === 'on') return `This page lost the unit, which can happen when the hotspot starts. Join ${name}, then reload this page.`
  return `This page lost the unit, which is expected when your phone is on the hotspot. Join ${name} again, then reload this page.`
}

function doneText(kind: Kind, job: Job): string {
  if (kind === 'off') return 'The hotspot is off.'
  if (kind === 'on') return 'The hotspot is on.'
  if (nothingToChange(job)) return 'Nothing changed. The hotspot already has these settings.'
  return props.hotspot.active ? 'Saved. The hotspot restarted.' : 'Saved. The change applies when the hotspot next starts.'
}

const working = computed(() => {
  if (running.value === 'off') return 'Turning the hotspot off.'
  if (running.value === 'on') return 'Turning the hotspot on.'
  return props.hotspot.active ? 'Saving. The hotspot is restarting.' : 'Saving.'
})

async function apply(kind: Kind, body: HotspotChange) {
  if (running.value) return
  notice.value = null
  forget()
  running.value = kind
  const mayLoseTheUnit = props.hotspot.active || kind === 'on'
  const name = body.name ?? props.hotspot.name
  try {
    const { data } = await api.POST('/api/v1/network/hotspot', { body })
    if (left) return
    following = followJob((data as { id: string }).id)
    const job = await following.done
    if (left) return
    if (job === null) {
      notice.value = {
        type: 'warning',
        text: "The device hasn't reported whether the change was made. Reload this page in a minute to check.",
      }
    } else if (job.status === 'succeeded') {
      notice.value = { type: 'success', text: doneText(kind, job) }
      emit('changed')
    } else {
      const text = saved(job) ? "The settings were saved, but the hotspot didn't restart." : "The change wasn't made."
      notice.value = { type: 'error', text, log: job.log }
      emit('changed') // even a failed job may have saved the settings; the page shows what the device has
    }
  } catch (error) {
    if (left) return
    // A request that fails after the device accepted the change is the hotspot going away under this page
    const lost = error instanceof ApiError && error.status === 0 && mayLoseTheUnit && following !== null
    notice.value = lost ? { type: 'info', text: lostText(kind, name) } : { type: 'error', text: messageOf(error) }
  } finally {
    following = null
    running.value = null
    resetSwitches()
  }
}

const nameOpen = ref(false)
const passwordOpen = ref(false)

// Turning off, hiding, and showing the name again ask first; turning on does not
type Ask = 'off' | 'hide' | 'unhide'
const ask = ref<Ask>('off')
const askOpen = ref(false)
const asks = computed(() => ({
  off: {
    title: 'Turn off the hotspot?',
    text: lines(TURN_OFF, props.onHotspot && ON_IT),
    confirm: 'Turn off',
  },
  hide: {
    title: 'Hide the hotspot name?',
    text: lines(
      props.hotspot.active && RESTART,
      join(HIDING, ANDROID),
      props.hotspot.active && props.onHotspot && ON_IT,
    ),
    confirm: 'Hide the name',
  },
  unhide: {
    title: 'Show the hotspot name?',
    text: restart.value || '',
    confirm: 'Show the name',
  },
}))

// What the two switches show. A tap changes the browser's checkbox at once, whatever the page then decides, so
// the switches keep their own value and go back to the device's whenever a question is declined or a job ends;
// otherwise the next tap would only flip the checkbox back, and say nothing.
const enabledSwitch = ref(props.hotspot.enabled)
const hiddenSwitch = ref(props.hotspot.hidden)
function resetSwitches() {
  enabledSwitch.value = props.hotspot.enabled
  hiddenSwitch.value = props.hotspot.hidden
}
watch(() => [props.hotspot.enabled, props.hotspot.hidden], resetSwitches)
watch(askOpen, (isOpen) => {
  if (!isOpen) resetSwitches()
})

function toggleEnabled(on: boolean | null) {
  if (on) {
    void apply('on', { enabled: true })
  } else {
    ask.value = 'off'
    askOpen.value = true
  }
}

function toggleHidden(hide: boolean | null) {
  ask.value = hide ? 'hide' : 'unhide'
  if (!hide && !props.hotspot.active) void apply('hidden', { hidden: false }) // nothing to warn about
  else askOpen.value = true
}

function confirmed() {
  if (ask.value === 'off') void apply('off', { enabled: false })
  else void apply('hidden', { hidden: ask.value === 'hide' })
}
</script>

<template>
  <div>
    <v-switch
      label="Hotspot on"
      color="primary"
      hide-details
      v-model="enabledSwitch"
      :disabled="disabled"
      class="mb-2"
      @update:model-value="toggleEnabled"
    />

    <FactRow label="Name" :value="hotspot.name" copy="hotspot name" class="mb-4">
      <template #actions>
        <v-btn
          variant="text"
          color="primary"
          size="large"
          aria-label="Change the hotspot name"
          :disabled="disabled"
          @click="nameOpen = true"
        >
          Change
        </v-btn>
      </template>
    </FactRow>

    <FactRow
      label="Password"
      :value="hasPassword ? (revealed === undefined ? '••••••••' : revealed || 'No password is set.') : 'None. Anyone nearby can join.'"
      :copy="revealed ? 'hotspot password' : undefined"
      class="mb-4"
    >
      <template #actions>
        <template v-if="hasPassword">
          <v-btn
            v-if="revealed === undefined"
            variant="text"
            color="primary"
            size="large"
            aria-label="Show the hotspot password"
            :loading="asking"
            :disabled="disabled || asking"
            @click="show"
          >
            Show
          </v-btn>
          <v-btn
            v-else
            variant="text"
            color="primary"
            size="large"
            aria-label="Hide the hotspot password"
            @click="forget"
          >
            Hide
          </v-btn>
          <v-btn
            variant="text"
            color="primary"
            size="large"
            aria-label="Change the hotspot password"
            :disabled="disabled"
            @click="passwordOpen = true"
          >
            Change
          </v-btn>
        </template>
        <v-btn
          v-else
          variant="text"
          color="primary"
          size="large"
          aria-label="Set a password for the hotspot"
          :disabled="disabled"
          @click="passwordOpen = true"
        >
          Set a password
        </v-btn>
      </template>
    </FactRow>

    <v-switch
      label="Hide the name"
      color="primary"
      hide-details
      v-model="hiddenSwitch"
      :disabled="disabled"
      class="mb-4"
      @update:model-value="toggleHidden"
    />

    <div class="mb-4">
      <div class="text-body-2 text-secondary">Address</div>
      <div class="text-body-1 text-break">http://{{ hotspot.address }}/</div>
      <div class="text-body-1 text-break">http://{{ localName }}/</div>
    </div>

    <v-alert v-if="busy" type="info" class="mb-4">{{ working }}</v-alert>
    <v-alert v-else-if="notice" :type="notice.type" class="mb-4">
      {{ notice.text }}
      <pre v-if="notice.log?.length" class="text-body-2 mt-2 text-wrap">{{ notice.log.join('\n') }}</pre>
    </v-alert>

    <v-alert v-if="locked && !busy" type="info" class="mb-4">
      {{ lockedByJob ? 'Wait for the Wi-Fi change to finish.' : 'Finish or cancel the Wi-Fi join first.' }}
    </v-alert>

    <p class="text-body-2 text-secondary">
      A hotspot on a pole is visible to anyone passing, and public Wi-Fi maps record where network names are seen.
      Hiding the name reduces that; only turning the hotspot off prevents it.
    </p>

    <HotspotField
      v-model="nameOpen"
      title="Change the hotspot name"
      label="New name"
      :warning="nameWarning"
      :rule="nameRule"
      :initial="hotspot.name"
      confirm-text="Change name"
      @save="(name) => apply('name', { name })"
    />
    <HotspotField
      v-model="passwordOpen"
      :title="hasPassword ? 'Change the hotspot password' : 'Set a password'"
      label="New password"
      :warning="passwordWarning"
      :rule="passwordRule"
      :confirm-text="hasPassword ? 'Change password' : 'Set password'"
      @save="(password) => apply('password', { password })"
    />
    <ConfirmDialog
      v-model="askOpen"
      :title="asks[ask].title"
      :text="asks[ask].text"
      :confirm-text="asks[ask].confirm"
      confirm-color="primary"
      @confirm="confirmed"
    />
  </div>
</template>
