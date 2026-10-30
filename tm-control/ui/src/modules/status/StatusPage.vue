<!--
  The Status page (GET /status): one sentence that sums up the device, then each group of checks. It checks again
  every 10 seconds while the page is visible, and replaces the list in place. Admins can restart a unit a check names
  (POST /services/{unit}/restart, after a confirmation) and re-scan the hardware (POST /status/rescan); viewers see
  the same checks without buttons.
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import CheckList from '../../components/CheckList.vue'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { ago } from '../../components/relative-time'
import { MARKS, type Note, verdict } from '../../components/status'
import { useSession } from '../../stores/session'
import { restartFor } from './restarts'

type Report = components['schemas']['Report']

const POLL_MS = 10_000

const session = useSession()
const report = ref<Report | null>(null)
const loadError = ref('')
const loading = ref(false)
const refreshing = ref(false) // the Refresh button was pressed; polls don't spin it

// "Checked ... ago" counts from when this page received the report, on this browser's clock. Comparing the report's
// generated_at with this browser's clock instead would be wrong whenever the device's clock is, which is one of the
// things this page reports.
const receivedAt = ref(Date.now())
const now = ref(Date.now())
const checked = computed(() => `Checked ${ago((now.value - receivedAt.value) / 1000)}`)

const summary = computed(() => (report.value ? verdict(report.value.summary) : null))

// Each button's last result, by unit or 'rescan'
const notes = ref<Record<string, Note>>({})
const busy = ref<string | null>(null)

function note(key: string, value: Note | null) {
  const next = { ...notes.value }
  if (value) next[key] = value
  else delete next[key]
  notes.value = next
}

// The buttons a report offers: the units of its restart fixes, and 'rescan'
function actionsIn(next: Report) {
  const fixes = next.groups.flatMap((group) => group.checks.map((check) => check.fix))
  return new Set(fixes.map((fix) => (fix?.kind === 'rescan' ? 'rescan' : fix?.kind === 'restart' ? fix.unit : null)))
}

function show(next: Report) {
  if (next.generated_at !== report.value?.generated_at) receivedAt.value = Date.now()
  report.value = next
  // A result stays while its button does. Once a check no longer offers that fix, the result is old news, and it
  // mustn't come back if the fix does.
  const offered = actionsIn(next)
  for (const key of Object.keys(notes.value)) if (!offered.has(key)) note(key, null)
}

async function load() {
  loading.value = true
  try {
    const { data } = await api.GET('/api/v1/status')
    show(data as Report)
    loadError.value = ''
  } catch (error) {
    loadError.value = messageOf(error)
  } finally {
    loading.value = false
  }
}

async function refresh() {
  refreshing.value = true
  await load()
  refreshing.value = false
}

// Restarting a unit, after the admin confirms
const confirming = ref<{ unit: string; text: string } | null>(null)
const confirmOpen = computed({
  get: () => confirming.value !== null,
  set: (open: boolean) => {
    if (!open) confirming.value = null
  },
})

function askRestart(unit: string) {
  const checks = report.value?.groups.flatMap((group) => group.checks) ?? []
  const fix = checks.map((check) => check.fix).find((f) => f?.kind === 'restart' && f.unit === unit)
  confirming.value = { unit, text: fix?.text ?? 'Restart' }
}

async function restart() {
  const target = confirming.value
  if (!target) return
  busy.value = target.unit
  note(target.unit, null)
  try {
    await api.POST('/api/v1/services/{unit}/restart', { params: { path: { unit: target.unit } } })
    note(target.unit, { text: restartFor(target.unit).result, error: false })
  } catch (error) {
    note(target.unit, { text: messageOf(error), error: true })
  } finally {
    busy.value = null
  }
}

async function rescan() {
  busy.value = 'rescan'
  note('rescan', null)
  try {
    const { data } = await api.POST('/api/v1/status/rescan')
    show(data as Report)
  } catch (error) {
    note('rescan', { text: messageOf(error), error: true })
  } finally {
    busy.value = null
  }
}

// Checking again: every 10 seconds while the page is visible, and at once when it becomes visible again
const visible = () => document.visibilityState === 'visible'
function whenVisible() {
  if (visible()) void load()
}
let poll: ReturnType<typeof setInterval> | undefined
let tick: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  void load()
  poll = setInterval(() => {
    if (visible() && !loading.value) void load()
  }, POLL_MS)
  tick = setInterval(() => (now.value = Date.now()), 1000)
  document.addEventListener('visibilitychange', whenVisible)
})

onBeforeUnmount(() => {
  clearInterval(poll)
  clearInterval(tick)
  document.removeEventListener('visibilitychange', whenVisible)
})
</script>

<template>
  <div>
    <h1 class="text-h5 text-primary mb-6">Status</h1>

    <v-alert v-if="loadError && !report" type="error">
      {{ loadError }}
      <template #append>
        <v-btn variant="text" @click="refresh">Try again</v-btn>
      </template>
    </v-alert>
    <v-progress-linear v-else-if="!report" indeterminate color="primary" />

    <template v-if="report && summary">
      <div class="d-flex align-center ga-3">
        <v-icon :icon="MARKS[summary.status].icon" :color="MARKS[summary.status].color" size="32" />
        <!-- A live region: a screen reader says the new verdict when a check changes it -->
        <p role="status" class="text-h5">{{ summary.text }}</p>
      </div>
      <div class="d-flex align-center justify-space-between flex-wrap ga-2 mt-1 mb-6">
        <p class="text-body-2 text-secondary">{{ checked }}</p>
        <v-btn variant="text" color="primary" min-height="44" :loading="refreshing" @click="refresh">Refresh</v-btn>
      </div>
      <!-- A later check failed: the list below is the last one that came back -->
      <v-alert v-if="loadError" type="error" class="mb-6">{{ loadError }}</v-alert>

      <CheckList
        v-for="group in report.groups"
        :key="group.id"
        :group="group"
        :admin="session.isAdmin"
        :busy="busy"
        :notes="notes"
        class="mb-8"
        @restart="askRestart"
        @rescan="rescan"
      />
    </template>

    <ConfirmDialog
      v-model="confirmOpen"
      :title="`${confirming?.text ?? ''}?`"
      :text="confirming ? restartFor(confirming.unit).notice : ''"
      :confirm-text="confirming?.text ?? ''"
      @confirm="restart"
    />
  </div>
</template>
