<!--
  The Cameras page (GET /cameras), for admins only: one row per camera in config.yml's sensors.cameras, then one per
  Frigate camera that no entry points at. Frigate owns each camera's name, streams, and zones; the page sets what the
  Traffic Monitor does with it. A row's bold name is the one saved with the data. Each row is an expansion panel, one
  open at a time: its header (Settings) opens CameraEdit inside the row to set Frigate's detection, capture, radar, and
  plates (PUT /cameras/{name}); a new Frigate camera's header (Add as new) opens it to add an entry (POST /cameras).
  The row's marks and its other buttons stay below, open or not. Every write answers with the whole new state, which
  replaces the page's. While Frigate isn't answering, or is in safe mode, its cameras can't be compared: a line says
  so, the settings stay editable. The actions that need the comparison (Point at this, Add as new, Use a neutral name,
  Remove) are offered only while `state.frigate` is "ok"; each confirms first, except Add as new. A refused action
  shows the API's message above the list, and a 409 or 404 loads the list again.
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ApiError, api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import CameraEdit, { type CameraSettings } from './CameraEdit.vue'
import { issueBoxes, pointChoices, rowState, zonesText, type CameraRow } from './rows'

type CamerasState = components['schemas']['CamerasState']

const UNAVAILABLE: Record<string, string> = {
  down: "Frigate isn't answering, so its cameras can't be compared. You can still change a camera's settings.",
  safe_mode:
    "Frigate is in safe mode, with no cameras; see the Status page. You can still change a camera's settings.",
}

// A row that is off in Frigate carries a chip; the other states say what is wrong in a sentence (see `sentence`)
const OFF_CHIP = { text: 'Off in Frigate', color: 'warning' }

const state = ref<CamerasState | null>(null)
const loadError = ref('')
const notice = ref('') // a change that could not be finished, shown above the list

async function load() {
  loadError.value = ''
  try {
    const { data } = await api.GET('/api/v1/cameras')
    state.value = data as CamerasState
  } catch (error) {
    loadError.value = messageOf(error)
  }
}

onMounted(load)

function keyOf(row: CameraRow) {
  return row.name ?? row.frigate_camera
}

// A row's own id among the panels: an entry by its name, a new Frigate camera by Frigate's
function rowId(row: CameraRow) {
  return row.name ?? `frigate:${row.frigate_camera}`
}

// Frigate's name goes beside the bold key when the two differ; a Frigate camera with no entry is its own bold name
function frigateName(row: CameraRow) {
  return row.name !== null && row.name !== row.frigate_camera ? row.frigate_camera : ''
}

function chipOf(row: CameraRow) {
  return rowState(row) === 'off' ? OFF_CHIP : undefined
}

// The cameras the Status page's checks report, counted above the list; each row's boxes say why
const attention = computed(() => {
  const rows = (state.value?.rows ?? []).filter((row) => row.issues.length > 0)
  if (rows.length === 0) return null
  const error = rows.some((row) => row.issues.some((issue) => issue.level === 'error'))
  const text =
    rows.length === 1
      ? '1 camera needs attention. Each marked row says why.'
      : `${rows.length} cameras need attention. Each marked row says why.`
  return { type: error ? ('error' as const) : ('warning' as const), text }
})

// A row's two switches in words, Frigate's and the database's, then an entry's radar and plates. Frigate's is left out
// while it can't be read (Frigate down, or the camera gone); a Frigate camera with no entry isn't captured.
function settings(row: CameraRow) {
  const words = []
  if (row.detect !== null) words.push(`Frigate detection: ${row.detect ? 'on' : 'off'}`)
  words.push(`Database capture: ${row.enabled ? 'on' : 'off'}`)
  if (row.name === null) return words
  words.push(`Radar: ${row.camera_radar ?? 'none'}`)
  if (state.value?.plates) words.push(`Plates: ${row.plate_recognizer ? 'on' : 'off'}`)
  return words
}

// The row's zones, unless Frigate can't be compared or a box already says what is wrong with them
function frigateLine(row: CameraRow) {
  if (rowState(row) === 'unknown' || row.issues.some((issue) => issue.code === 'zones')) return ''
  return zonesText(row)
}

// An action that sends a request needs Frigate's cameras to compare, so it is offered only while Frigate answers
const compared = computed(() => state.value?.frigate === 'ok')

// A row opens to its settings form, except a new Frigate camera while it can't be added
function opens(row: CameraRow) {
  return row.name !== null || compared.value
}

// Whether a row has anything under its header: marks, its zones, or buttons for what to do with it
function hasBody(row: CameraRow) {
  return issueBoxes(row).length > 0 || frigateLine(row) !== '' || actions(row).length > 0
}

// The buttons under a row's header, each with what it does; none while Frigate can't be compared
function actions(row: CameraRow) {
  if (!compared.value || !state.value) return []
  const list: { text: string; color: string; variant: 'outlined' | 'text'; pending: Pending }[] = []
  for (const entry of pointChoices(row, state.value.rows)) {
    const pending = { kind: 'point' as const, name: entry.name ?? '', to: row.frigate_camera }
    list.push({ text: `Point ${entry.name} at this`, color: 'primary', variant: 'outlined', pending })
  }
  if (row.name !== null && row.neutral === false) {
    list.push({ text: 'Use a neutral name', color: 'primary', variant: 'text', pending: { kind: 'neutral', name: row.name } })
  }
  if (row.name !== null && (rowState(row) === 'gone' || rowState(row) === 'duplicate')) {
    list.push({ text: 'Remove', color: 'error', variant: 'text', pending: { kind: 'remove', name: row.name } })
  }
  return list
}

// Whether a refusal means the page's list is out of date: the file or Frigate changed (409), or the camera is gone (404)
function stale(error: unknown) {
  return error instanceof ApiError && (error.status === 409 || error.status === 404)
}

// Run one request, show its answer as the page's state, and say why it failed otherwise; a stale list is loaded again
async function perform(send: () => Promise<{ data?: unknown }>) {
  notice.value = ''
  try {
    const { data } = await send()
    state.value = data as CamerasState
    expanded.value = null // the row may be renamed or gone
    return true
  } catch (error) {
    notice.value = messageOf(error)
    if (stale(error)) await load()
    return false
  }
}

// What the confirm dialog is about, kept after it closes so its words don't change while it fades
type Pending =
  | { kind: 'point'; name: string; to: string }
  | { kind: 'neutral'; name: string }
  | { kind: 'remove'; name: string }
const pending = ref<Pending | null>(null)
const confirmOpen = ref(false)

function ask(next: Pending) {
  pending.value = next
  confirmOpen.value = true
}

const confirmWords = computed(() => {
  const what = pending.value
  if (what?.kind === 'point') {
    return {
      title: `Point ${what.name} at ${what.to}?`,
      text: `Events from ${what.to} will be recorded as ${what.name}, with the same settings. Nothing already recorded changes.`,
      confirmText: 'Point',
      color: 'primary',
    }
  }
  if (what?.kind === 'neutral') {
    return {
      title: `Use a neutral name for ${what.name}?`,
      text:
        `New records will be saved under a name like camera_1_3fa9c2 instead of ${what.name}. ` +
        `Records already saved keep the name ${what.name}, and the dashboards' charts start again under the new name. ` +
        'A new deployment starts for this camera.',
      confirmText: 'Use a neutral name',
      color: 'primary',
    }
  }
  return {
    title: `Remove ${what?.name ?? ''}?`,
    text: 'Its settings are removed from config.yml. Records already saved are kept.',
    confirmText: 'Remove',
    color: 'error',
  }
})

async function confirmed() {
  const what = pending.value
  if (!what) return
  const path = { name: what.name }
  if (what.kind === 'point') {
    await perform(() => api.POST('/api/v1/cameras/{name}/frigate-camera', { params: { path }, body: { to: what.to } }))
  } else if (what.kind === 'neutral') {
    await perform(() => api.POST('/api/v1/cameras/{name}/neutral-name', { params: { path } }))
  } else {
    await perform(() => api.DELETE('/api/v1/cameras/{name}', { params: { path } }))
  }
}

// The open row (its rowId), whose CameraEdit edits one entry's settings or adds a new Frigate camera. The row is
// looked up each time, so the form follows the page's state. Opening another row, or closing this one, clears what
// the last save said.
const expanded = ref<string | null>(null)
const editRow = computed(() => state.value?.rows.find((row) => rowId(row) === expanded.value) ?? null)
const saving = ref(false)
const saveError = ref('')
const radarError = ref('')

watch(expanded, () => {
  saveError.value = ''
  radarError.value = ''
})

function setOpen(row: CameraRow, open: boolean) {
  if (open) expanded.value = rowId(row)
  else if (expanded.value === rowId(row)) expanded.value = null
}

async function save(settings: CameraSettings, detect: boolean | null) {
  const row = editRow.value
  if (row === null) return
  const target: { name: string } | { frigate: string } =
    row.name === null ? { frigate: row.frigate_camera } : { name: row.name }
  saving.value = true
  saveError.value = ''
  radarError.value = ''
  try {
    const { data } =
      'name' in target
        ? await api.PUT('/api/v1/cameras/{name}', { params: { path: { name: target.name } }, body: settings })
        : await api.POST('/api/v1/cameras', { body: { frigate_camera: target.frigate, ...settings } })
    state.value = data as CamerasState
    // Frigate's switch after config.yml's settings: a refusal leaves those saved, and the form says why
    if (detect !== null && 'name' in target) {
      const { data: detected } = await api.PUT('/api/v1/cameras/{name}/frigate-detection', {
        params: { path: { name: target.name } },
        body: { enabled: detect },
      })
      state.value = detected as CamerasState
    }
    expanded.value = null
  } catch (error) {
    const message = messageOf(error)
    const field = error instanceof ApiError ? (error.detail as { field?: string } | null)?.field : undefined
    if (error instanceof ApiError && error.status === 422 && field === 'camera_radar') {
      radarError.value = message
    } else {
      saveError.value = message
    }
    // The file or Frigate changed under the form, or the camera is gone: load again; a row that has gone closes and
    // the page says why
    if (stale(error)) {
      await load()
      if (!editRow.value) {
        expanded.value = null
        notice.value = message
      }
    }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div>
    <h1 class="text-h5 text-primary mb-6">Cameras</h1>

    <v-alert v-if="loadError" type="error" class="mb-6">
      {{ loadError }}
      <template #append>
        <v-btn variant="text" @click="load">Try again</v-btn>
      </template>
    </v-alert>
    <v-progress-linear v-else-if="!state" indeterminate color="primary" />

    <template v-if="state">
      <p class="text-body-1 mb-4">
        Frigate owns each camera: its name, streams, and zones. This page sets what the Traffic Monitor does with it.
        The name in bold is the one saved with the data. Frigate's name stays on this device.
      </p>
      <p class="text-body-1 mb-4">
        <a href="/frigate/">Open Frigate</a> to add a camera or change a camera's name, streams, or zones.
      </p>

      <v-alert v-if="UNAVAILABLE[state.frigate]" type="warning" class="mb-4">{{ UNAVAILABLE[state.frigate] }}</v-alert>
      <v-alert v-if="attention" :type="attention.type" variant="tonal" class="mb-4" data-summary>{{
        attention.text
      }}</v-alert>
      <v-alert v-if="notice" type="warning" closable class="mb-4" @click:close="notice = ''">{{ notice }}</v-alert>

      <v-expansion-panels v-model="expanded" variant="accordion" flat class="border rounded">
        <v-expansion-panel
          v-for="(row, index) in state.rows"
          :key="rowId(row)"
          :value="rowId(row)"
          :readonly="!opens(row)"
          :class="{ 'border-t': index > 0 }"
          bg-color="background"
        >
          <v-expansion-panel-title :hide-actions="!opens(row)" class="py-3">
            <div class="flex-grow-1">
              <div class="d-flex flex-wrap align-center ga-2">
                <span class="text-subtitle-1 font-weight-bold">{{ keyOf(row) }}</span>
                <span v-if="frigateName(row)" class="text-body-2 text-secondary">Frigate: {{ frigateName(row) }}</span>
                <v-chip v-if="chipOf(row)" size="small" variant="outlined" :color="chipOf(row)?.color">
                  {{ chipOf(row)?.text }}
                </v-chip>
              </div>
              <div class="d-flex flex-wrap text-body-2 mt-1">
                <span v-for="words in settings(row)" :key="words" class="me-4">{{ words }}</span>
              </div>
            </div>
            <template #actions="{ expanded: isOpen }">
              <span class="text-body-2 text-primary ms-2 me-1 text-no-wrap">{{
                row.name === null ? 'Add as new' : 'Settings'
              }}</span>
              <v-icon :icon="isOpen ? '$collapse' : '$expand'" color="primary" />
            </template>
          </v-expansion-panel-title>
          <v-expansion-panel-text>
            <CameraEdit
              :open="expanded === rowId(row)"
              :row="row"
              :radars="state.radars"
              :plates="state.plates"
              :frigate="compared"
              :adding="row.name === null"
              :saving="saving"
              :error="expanded === rowId(row) ? saveError : ''"
              :radar-error="expanded === rowId(row) ? radarError : ''"
              @update:open="(open: boolean) => setOpen(row, open)"
              @save="save"
            />
          </v-expansion-panel-text>
          <div v-if="hasBody(row)" class="px-6 pb-4">
            <v-alert
              v-for="box in issueBoxes(row)"
              :key="box.text"
              :type="box.level"
              variant="tonal"
              density="compact"
              class="mb-2 text-body-2"
              data-issue
            >
              {{ box.text }}
              <a v-if="box.link" :href="box.link.href" class="d-inline-block">{{ box.link.text }}</a>
            </v-alert>
            <div v-if="frigateLine(row)" class="text-body-2 text-secondary">{{ frigateLine(row) }}</div>
            <div v-if="actions(row).length" class="d-flex flex-wrap ga-2 mt-2" data-actions>
              <v-btn
                v-for="action in actions(row)"
                :key="action.text"
                :variant="action.variant"
                :color="action.color"
                min-height="44"
                @click="ask(action.pending)"
              >
                {{ action.text }}
              </v-btn>
            </div>
          </div>
        </v-expansion-panel>
      </v-expansion-panels>
      <p v-if="!state.rows.length" class="text-body-1 mt-4">
        No cameras are listed in config.yml, and Frigate has none.
      </p>

      <ConfirmDialog
        v-model="confirmOpen"
        :title="confirmWords.title"
        :text="confirmWords.text"
        :confirm-text="confirmWords.confirmText"
        :confirm-color="confirmWords.color"
        @confirm="confirmed"
      />
    </template>
  </div>
</template>
