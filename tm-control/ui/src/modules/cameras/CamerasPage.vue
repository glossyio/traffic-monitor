<!--
  The Cameras page (GET /cameras), for admins only: one row per camera in config.yml's sensors.cameras, then one per
  Frigate camera that no entry points at. Frigate owns each camera's name, streams, and zones; the page sets what the
  Traffic Monitor does with it. A row's bold name is the one saved with the data. Edit opens CameraEdit to set record,
  radar, and plates (PUT /cameras/{name}). Every write answers with the whole new state, which replaces the page's.
  While Frigate isn't answering, or is in safe mode, its cameras can't be compared: a line says so, the settings stay
  editable; the actions that need the comparison are to be offered only while `state.frigate` is "ok".
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ApiError, api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import CameraEdit, { type CameraSettings } from './CameraEdit.vue'
import { rowState, zonesText, type Row, type RowState } from './rows'

type CamerasState = components['schemas']['CamerasState']

const UNAVAILABLE: Record<string, string> = {
  down: "Frigate isn't answering, so its cameras can't be compared. You can still change a camera's settings.",
  safe_mode:
    "Frigate is in safe mode, with no cameras; see the Status page. You can still change a camera's settings.",
}

// Each state's chip: its words and color. In step and unknown rows have none.
const CHIPS: Partial<Record<RowState, { text: string; color: string }>> = {
  off: { text: 'Off in Frigate', color: 'warning' },
  gone: { text: 'Not in Frigate', color: 'warning' },
  new: { text: 'Not recorded', color: 'warning' },
}

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

function keyOf(row: Row) {
  return row.name ?? row.frigate_camera
}

// Frigate's name goes beside the bold key when the two differ; a Frigate camera with no entry is its own bold name
function frigateName(row: Row) {
  return row.name !== null && row.name !== row.frigate_camera ? row.frigate_camera : ''
}

function chipOf(row: Row) {
  if (rowState(row) === 'duplicate') return { text: `Same Frigate camera as ${row.duplicate_of}`, color: 'warning' }
  return CHIPS[rowState(row)]
}

// A row's settings in words, for entries only
function settings(row: Row) {
  const words = [`Record events: ${row.enabled ? 'on' : 'off'}`, `Radar: ${row.camera_radar ?? 'none'}`]
  if (state.value?.plates) words.push(`Plates: ${row.plate_recognizer ? 'on' : 'off'}`)
  return words
}

// Whether the row says anything about Frigate's side
function frigateLine(row: Row) {
  return rowState(row) === 'unknown' ? '' : zonesText(row)
}

// Editing one entry's settings in CameraEdit. The row is looked up by name, so the dialog follows the page's state.
const editOpen = ref(false)
const editName = ref<string | null>(null)
const editRow = computed(() => state.value?.rows.find((row) => row.name === editName.value) ?? null)
const saving = ref(false)
const saveError = ref('')
const radarError = ref('')

function openEdit(row: Row) {
  editName.value = row.name
  saveError.value = ''
  radarError.value = ''
  editOpen.value = true
}

async function save(settings: CameraSettings) {
  const name = editName.value
  if (name === null) return
  saving.value = true
  saveError.value = ''
  radarError.value = ''
  try {
    const { data } = await api.PUT('/api/v1/cameras/{name}', { params: { path: { name } }, body: settings })
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
    // The file changed under the dialog: load again; a camera that has gone leaves the dialog and says so on the page
    if (error instanceof ApiError && error.status === 409) {
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
            <div v-if="frigateLine(row)" class="text-body-2 text-secondary mt-1">{{ frigateLine(row) }}</div>
            <template v-if="row.name !== null" #append>
              <v-btn variant="outlined" color="primary" min-height="44" @click="openEdit(row)">Edit</v-btn>
            </template>
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
        :adding="false"
        :saving="saving"
        :error="saveError"
        :radar-error="radarError"
        @save="save"
      />
    </template>
  </div>
</template>
