<!--
  The Cameras page (GET /cameras), for admins only: one row per camera in config.yml's sensors.cameras, then one per
  Frigate camera that no entry points at. Frigate owns each camera's name, streams, and zones; the page sets what the
  Traffic Monitor does with it. A row's bold name is the one saved with the data. Edit opens CameraEdit to set record,
  radar, and plates (PUT /cameras/{name}). Every write answers with the whole new state, which replaces the page's.
  While Frigate isn't answering, or is in safe mode, its cameras can't be compared: a line says so, the settings stay
  editable. The actions that need the comparison (Point at this, Add as new, Use a neutral name, Remove) are offered
  only while `state.frigate` is "ok"; each confirms first, except Add as new, which opens CameraEdit. A refused action
  shows the API's message above the list, and a 409 or 404 loads the list again.
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import CameraEdit, { type CameraSettings } from './CameraEdit.vue'
import { pointChoices, rowState, zonesText, type CameraRow } from './rows'

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

// Frigate's name goes beside the bold key when the two differ; a Frigate camera with no entry is its own bold name
function frigateName(row: CameraRow) {
  return row.name !== null && row.name !== row.frigate_camera ? row.frigate_camera : ''
}

function chipOf(row: CameraRow) {
  return rowState(row) === 'off' ? OFF_CHIP : undefined
}

// What is out of step on a row, in words; empty for a row that is in step
function sentence(row: CameraRow) {
  switch (rowState(row)) {
    case 'new':
      return `${row.frigate_camera} is new in Frigate and isn't recorded.`
    case 'gone':
      return `Frigate no longer has ${row.frigate_camera}.`
    case 'duplicate':
      return `${row.duplicate_of} already records this Frigate camera.`
    default:
      return ''
  }
}

// A row's settings in words, for entries only
function settings(row: CameraRow) {
  const words = [`Record events: ${row.enabled ? 'on' : 'off'}`, `Radar: ${row.camera_radar ?? 'none'}`]
  if (state.value?.plates) words.push(`Plates: ${row.plate_recognizer ? 'on' : 'off'}`)
  return words
}

// Whether the row says anything about Frigate's side
function frigateLine(row: CameraRow) {
  return rowState(row) === 'unknown' ? '' : zonesText(row)
}

// An action that sends a request needs Frigate's cameras to compare, so it is offered only while Frigate answers
const compared = computed(() => state.value?.frigate === 'ok')

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

// Editing one entry's settings, or adding a new Frigate camera, in CameraEdit. The row is looked up each time, so the
// dialog follows the page's state; an entry is found by its name, a new camera by Frigate's.
const editOpen = ref(false)
const editing = ref<{ name: string } | { frigate: string } | null>(null)
const editRow = computed(() => {
  const target = editing.value
  if (!target || !state.value) return null
  if ('name' in target) return state.value.rows.find((row) => row.name === target.name) ?? null
  return state.value.rows.find((row) => row.name === null && row.frigate_camera === target.frigate) ?? null
})
const saving = ref(false)
const saveError = ref('')
const radarError = ref('')

function openEdit(row: CameraRow) {
  editing.value = row.name === null ? { frigate: row.frigate_camera } : { name: row.name }
  saveError.value = ''
  radarError.value = ''
  editOpen.value = true
}

async function save(settings: CameraSettings) {
  const target = editing.value
  if (target === null) return
  saving.value = true
  saveError.value = ''
  radarError.value = ''
  try {
    const { data } =
      'name' in target
        ? await api.PUT('/api/v1/cameras/{name}', { params: { path: { name: target.name } }, body: settings })
        : await api.POST('/api/v1/cameras', { body: { frigate_camera: target.frigate, ...settings } })
    state.value = data as CamerasState
    editOpen.value = false
  } catch (error) {
    const message = messageOf(error)
    const field = error instanceof ApiError ? (error.detail as { field?: string } | null)?.field : undefined
    if (error instanceof ApiError && error.status === 422 && field === 'camera_radar') {
      radarError.value = message
    } else {
      saveError.value = message
    }
    // The file or Frigate changed under the dialog, or the camera is gone: load again; a camera that has gone leaves
    // the dialog and says so
    if (stale(error)) {
      await load()
      if (!editRow.value) {
        editOpen.value = false
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
      <p class="text-body-1 mb-4"><a href="/frigate/">Open Frigate</a> to change a camera's name, streams, or zones.</p>

      <v-alert v-if="UNAVAILABLE[state.frigate]" type="warning" class="mb-4">{{ UNAVAILABLE[state.frigate] }}</v-alert>
      <v-alert v-if="notice" type="warning" closable class="mb-4" @click:close="notice = ''">{{ notice }}</v-alert>

      <v-list class="border rounded py-0" bg-color="background">
        <template v-for="(row, index) in state.rows" :key="row.name ?? `frigate:${row.frigate_camera}`">
          <v-divider v-if="index > 0" />
          <v-list-item class="py-3">
            <div class="d-flex flex-wrap align-center ga-2">
              <span class="text-subtitle-1 font-weight-bold">{{ keyOf(row) }}</span>
              <span v-if="frigateName(row)" class="text-body-2 text-secondary">Frigate: {{ frigateName(row) }}</span>
              <v-chip v-if="chipOf(row)" size="small" variant="outlined" :color="chipOf(row)?.color">
                {{ chipOf(row)?.text }}
              </v-chip>
            </div>
            <div v-if="row.name !== null" class="d-flex flex-wrap text-body-2 mt-1">
              <span v-for="words in settings(row)" :key="words" class="me-4">{{ words }}</span>
            </div>
            <div v-if="sentence(row)" class="text-body-2 mt-1">{{ sentence(row) }}</div>
            <div v-if="frigateLine(row)" class="text-body-2 text-secondary mt-1">{{ frigateLine(row) }}</div>
            <div class="d-flex flex-wrap ga-2 mt-2">
              <v-btn v-if="row.name !== null" variant="outlined" color="primary" min-height="44" @click="openEdit(row)">
                Edit
              </v-btn>
              <template v-if="compared">
                <v-btn
                  v-for="entry in pointChoices(row, state.rows)"
                  :key="entry.name ?? ''"
                  variant="outlined"
                  color="primary"
                  min-height="44"
                  @click="ask({ kind: 'point', name: entry.name ?? '', to: row.frigate_camera })"
                >
                  Point {{ entry.name }} at this
                </v-btn>
                <v-btn
                  v-if="rowState(row) === 'new'"
                  variant="outlined"
                  color="primary"
                  min-height="44"
                  @click="openEdit(row)"
                >
                  Add as new
                </v-btn>
                <v-btn
                  v-if="row.name !== null && row.neutral === false"
                  variant="text"
                  color="primary"
                  min-height="44"
                  @click="ask({ kind: 'neutral', name: row.name })"
                >
                  Use a neutral name
                </v-btn>
                <v-btn
                  v-if="row.name !== null && (rowState(row) === 'gone' || rowState(row) === 'duplicate')"
                  variant="text"
                  color="error"
                  min-height="44"
                  @click="ask({ kind: 'remove', name: row.name })"
                >
                  Remove
                </v-btn>
              </template>
            </div>
          </v-list-item>
        </template>
      </v-list>
      <p v-if="!state.rows.length" class="text-body-1 mt-4">
        No cameras are listed in config.yml, and Frigate has none.
      </p>

      <CameraEdit
        v-if="editRow"
        v-model:open="editOpen"
        :row="editRow"
        :radars="state.radars"
        :plates="state.plates"
        :adding="editRow.name === null"
        :saving="saving"
        :error="saveError"
        :radar-error="radarError"
        @save="save"
      />
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
