<!--
  One entered secret, as GET /secrets lists it: whether it's set, a field for a new value (hidden unless the person
  asks to see what they typed), Save (POST /secrets/{name}), and Remove (DELETE /secrets/{name}) after a confirmation.
  Each starts the set-secret root job, which restarts the apps that read the value; the form waits for it and says how
  it went. The value is never shown back: the field starts empty and is emptied once the device has it. Emits
  `changed` when a job has finished, so the page can load the secrets' state again.
-->
<script setup lang="ts">
import { mdiEye, mdiEyeOff } from '@mdi/js'
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { api, messageOf } from '../api/client'
import type { components } from '../api/schema'
import type { Job } from '../api/types'
import ConfirmDialog from './ConfirmDialog.vue'
import { followJob } from './jobs'

type SecretState = components['schemas']['SecretState']

const props = defineProps<{ secret: SecretState }>()
const emit = defineEmits<{ changed: [] }>()

// The set-secret job can wait out two restarts of up to two minutes each, longer than setup's two minutes
const SECRET_JOB_DEADLINE_MS = 300_000

const APPS: Record<string, string> = {
  'node-red-tm.service': 'Node-RED',
  'plate-recognizer.service': 'Plate Recognizer',
  'frigate.service': 'Frigate',
}

// About how long each app takes to restart, in seconds; a secret that restarts two apps waits for both
const RESTART_SECONDS: Record<string, number> = {
  'node-red-tm.service': 30,
  'plate-recognizer.service': 30,
  'frigate.service': 60,
}

// What stops working while the secret isn't set, by secret name
const CONSEQUENCES: Record<string, string> = {
  thingsboard_access_token: 'The upload to ThingsBoard stops until a token is set again.',
  plate_recognizer_token: "Plates aren't read until it's set again.",
  plate_recognizer_license_key: "Plates aren't read until it's set again.",
  frigate_plus_api_key:
    "Snapshots can't be sent to Frigate+ until a key is set again. " +
    'A Frigate+ model already on the device keeps running.',
}

const apps = computed(() => props.secret.restarts.map((unit) => APPS[unit] ?? unit).join(' and '))
function describe(seconds: number) {
  if (seconds <= 30) return 'about thirty seconds'
  if (seconds <= 60) return 'about a minute'
  if (seconds <= 90) return 'about a minute and a half'
  return 'about two minutes'
}

const restartNote = computed(() => {
  const units = props.secret.restarts
  const seconds = units.reduce((sum, unit) => sum + (RESTART_SECONDS[unit] ?? 30), 0) // an unlisted app: thirty
  const one = units.length === 1
  const note = `${apps.value} restart${one ? 's' : ''}, which takes ${describe(seconds)}.`
  // Frigate does the detecting, so nothing is counted until it's back
  return units.includes('frigate.service') ? `${note} Traffic isn't counted while it does.` : note
})

const stateLine = computed(() => {
  if (!props.secret.set) return 'Not set.'
  return props.secret.ends_with ? `Set, ending in ${props.secret.ends_with}.` : 'Set.'
})

const form = ref<{ validate: () => Promise<{ valid: boolean }>; resetValidation: () => void } | null>(null)
const value = ref('')
const shown = ref(false)
const entered = (text: string) => !!text.trim() || 'Enter a value, or leave this as it is.'

type Action = 'save' | 'remove'
const running = ref<Action | null>(null)
const error = ref('')
const result = ref<{ action: Action; job: Job | null } | null>(null) // job null: the device never reported
const confirmOpen = ref(false)

let left = false
let following: ReturnType<typeof followJob> | null = null
onBeforeUnmount(() => {
  left = true
  following?.cancel()
})

async function run(action: Action, start: () => Promise<{ data?: unknown }>) {
  if (running.value) return // one job at a time per secret; the buttons are disabled meanwhile too
  error.value = ''
  result.value = null
  running.value = action
  try {
    const { data } = await start()
    if (left) return
    // The device has the value, or is emptying it: either way, what was typed isn't kept on the page
    value.value = ''
    shown.value = false
    await nextTick()
    if (left) return // the page may be left during the tick, before anything would cancel the poll
    form.value?.resetValidation()
    following = followJob((data as { id: string }).id, SECRET_JOB_DEADLINE_MS)
    const job = await following.done
    if (left) return
    result.value = { action, job }
    if (job) emit('changed') // even a failed job may have written the value; the page shows what the device has
  } catch (failure) {
    error.value = messageOf(failure)
  } finally {
    running.value = null
  }
}

async function save() {
  if (!(await form.value?.validate())?.valid) return
  const body = { value: value.value }
  await run('save', () => api.POST('/api/v1/secrets/{name}', { params: { path: { name: props.secret.name } }, body }))
}

function remove() {
  void run('remove', () => api.DELETE('/api/v1/secrets/{name}', { params: { path: { name: props.secret.name } } }))
}

const restarted = computed(() => `${apps.value} restarted`)
const working = { save: 'Saving.', remove: 'Removing.' }
const done = { save: 'Saved', remove: 'Removed' }
const notDone = { save: "The value wasn't saved.", remove: "The value wasn't removed." }
// The job wrote the value, then an app's restart failed: its log line says so
const writtenOnly = {
  save: 'The value was saved, but a restart failed.',
  remove: 'The value was removed, but a restart failed.',
}
const written = (job: Job) => job.log.some((line) => line.endsWith('the secret is written'))
const unknown = {
  save: "The device hasn't reported whether the value was saved. Reload this page in a minute to check.",
  remove: "The device hasn't reported whether the value was removed. Reload this page in a minute to check.",
}
</script>

<template>
  <div>
    <h3 class="text-subtitle-1 font-weight-medium">{{ secret.title }}</h3>
    <p class="text-body-2 text-secondary mb-3">{{ stateLine }}</p>
    <v-form ref="form" :disabled="running !== null" @submit.prevent="save">
      <v-text-field
        v-model="value"
        :label="secret.title"
        :type="shown ? 'text' : 'password'"
        autocomplete="off"
        autocapitalize="none"
        spellcheck="false"
        :rules="[entered]"
        class="mb-2"
      >
        <template #append-inner>
          <v-btn
            :icon="shown ? mdiEyeOff : mdiEye"
            :aria-label="shown ? 'Hide' : 'Show'"
            variant="text"
            size="small"
            density="comfortable"
            @click="shown = !shown"
          />
        </template>
      </v-text-field>
      <div class="d-flex flex-wrap ga-3">
        <!-- A disabled v-form doesn't disable its buttons, so each one is disabled while either job runs -->
        <v-btn
          type="submit"
          color="primary"
          size="large"
          :loading="running === 'save'"
          :disabled="running !== null"
        >
          Save
        </v-btn>
        <v-btn
          v-if="secret.set"
          variant="outlined"
          color="primary"
          size="large"
          :loading="running === 'remove'"
          :disabled="running !== null"
          @click="confirmOpen = true"
        >
          Remove
        </v-btn>
      </div>
    </v-form>

    <!-- The job takes as long as the restarts, so the wait is said in words, not only by the spinner -->
    <v-alert v-if="running" type="info" class="mt-4">{{ working[running] }} {{ restartNote }}</v-alert>
    <v-alert v-if="error" type="error" class="mt-4">{{ error }}</v-alert>
    <template v-else-if="result">
      <v-alert v-if="result.job?.status === 'succeeded'" type="success" class="mt-4">
        {{ done[result.action] }}. {{ restarted }}.
      </v-alert>
      <v-alert v-else-if="result.job" type="error" class="mt-4">
        {{ (written(result.job) ? writtenOnly : notDone)[result.action] }}
        <pre v-if="result.job.log.length" class="text-body-2 mt-2 text-wrap">{{ result.job.log.join('\n') }}</pre>
      </v-alert>
      <v-alert v-else type="warning" class="mt-4">{{ unknown[result.action] }}</v-alert>
    </template>

    <ConfirmDialog
      v-model="confirmOpen"
      :title="`Remove the ${secret.title}?`"
      :text="`${restartNote} ${CONSEQUENCES[secret.name] ?? ''}`.trim()"
      confirm-text="Remove"
      @confirm="remove"
    />
  </div>
</template>
