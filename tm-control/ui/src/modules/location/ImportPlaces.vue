<!--
  Importing planned places from a CSV, the content of the page's dialog. The text is pasted, or read from a .csv file
  into the same box, where it can still be changed. Preview (POST /surveys/import with dry_run) lists the places the
  API read and, by line, what it couldn't. Import sends the same text again without dry_run, and is offered only when
  the preview found places and no errors: the API then creates every place, or none. Changing the text forgets the
  preview. Emits `imported` once places were added, and `close`.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import { bearingTitle, formatExact } from './coordinates'

type Bearing = components['schemas']['Bearing']
type ImportOut = components['schemas']['ImportOut']

// 64 KiB, the most the API takes (ImportIn's csv has max_length=65536). A file that size holds at most that many
// characters, so checking a file's bytes and a pasted text's characters against it both stay within the API's limit.
const MAX_LENGTH = 65536

const props = defineProps<{ sensors: Bearing[] }>()
const emit = defineEmits<{ imported: []; close: [] }>()

// The header's columns for this unit: the three place columns, then one per enabled sensor, named as in the settings
const columns = computed(() => ['description', 'lat', 'lon', ...props.sensors.map((s) => s.sensor_name)])

const text = ref('')
const fileError = ref('')
const sending = ref(false)
const error = ref('')
const preview = ref<ImportOut | null>(null)
const added = ref<number | null>(null) // how many places the import added, once it has

const tooLong = computed(() => text.value.length > MAX_LENGTH)
const canImport = computed(() => !!preview.value && preview.value.rows.length > 0 && !preview.value.errors.length)

// A changed text needs a new preview before it can be imported
watch(text, () => {
  preview.value = null
  error.value = ''
})

// The chosen file's text, into the box. Vuetify gives one file, or none when the choice is cleared.
async function read(file: File | File[] | null | undefined) {
  fileError.value = ''
  const chosen = Array.isArray(file) ? file[0] : file
  if (!chosen) return
  if (chosen.size > MAX_LENGTH) {
    fileError.value = 'The file is larger than 64 KiB. Split it into smaller files.'
    return
  }
  text.value = await chosen.text()
}

async function send(dryRun: boolean) {
  sending.value = true
  error.value = ''
  try {
    const { data } = await api.POST('/api/v1/surveys/import', { body: { csv: text.value, dry_run: dryRun } })
    const answer = data as ImportOut
    if (dryRun) {
      preview.value = answer
    } else {
      added.value = answer.created.length
      emit('imported')
    }
  } catch (failure) {
    error.value = messageOf(failure)
  } finally {
    sending.value = false
  }
}

function places(count: number) {
  return count === 1 ? '1 place' : `${count} places`
}
</script>

<template>
  <v-card color="surface" rounded="lg">
    <v-card-title class="text-h6 text-wrap pt-4">Import places</v-card-title>
    <v-card-text>
      <v-alert v-if="added !== null" type="success">Added {{ places(added) }}.</v-alert>

      <template v-else>
        <p class="text-body-1 mb-2">
          One place per line, after a header line. The columns are description, lat, and lon, then one per sensor,
          named as in the settings, with the way it faces: n, ne, e, se, s, sw, w, nw, or blank. Leave lat and lon
          blank for a place with no location. The places are added as planned.
        </p>
        <!-- A narrow screen breaks the header after a comma (<wbr>), not inside a sensor's name -->
        <p class="text-body-1 mb-6">
          This unit's header:
          <code class="text-break">
            <span v-for="(name, i) in columns" :key="name">{{ i ? ',' : '' }}<wbr v-if="i" />{{ name }}</span>
          </code>
        </p>

        <v-file-input
          label="CSV file"
          accept=".csv,text/csv"
          :error-messages="fileError"
          variant="outlined"
          :disabled="sending"
          class="mb-2"
          @update:model-value="read"
        />
        <v-textarea
          v-model="text"
          label="Places as CSV"
          hint="Or paste the lines here"
          persistent-hint
          :error-messages="tooLong ? 'The text is longer than 64 KiB. Split it into smaller files.' : ''"
          rows="5"
          autocomplete="off"
          spellcheck="false"
          variant="outlined"
          :disabled="sending"
        />

        <div v-if="sending" role="status" class="mt-4">
          <v-progress-linear indeterminate color="primary" />
        </div>

        <!-- The preview: what the API couldn't read, by line, then the places it could -->
        <template v-if="preview">
          <v-alert v-if="preview.errors.length" type="error" class="mt-6">
            <p class="mb-2">Fix these lines, then preview again. Nothing is imported while any line has a problem.</p>
            <ul class="lines">
              <li v-for="problem in preview.errors" :key="problem.line">
                Line {{ problem.line }}: {{ problem.message }}
              </li>
            </ul>
          </v-alert>
          <p v-if="!preview.rows.length && !preview.errors.length" class="text-body-1 mt-6">
            There are no places in the text, only the header.
          </p>
          <template v-if="preview.rows.length">
            <h3 class="text-subtitle-1 font-weight-medium mt-6 mb-2">Places read ({{ preview.rows.length }})</h3>
            <ul class="lines d-flex flex-column ga-4">
              <li v-for="row in preview.rows" :key="row.line">
                <div class="text-body-2 text-secondary">Line {{ row.line }}</div>
                <div class="text-body-1 text-break">{{ row.description ?? 'No description' }}</div>
                <div class="text-body-2 text-no-wrap">{{ formatExact(row.lat, row.lon) }}</div>
                <div v-for="bearing in row.bearings" :key="bearing.sensor_name" class="text-body-2 text-break">
                  {{ bearing.sensor_name }} faces {{ bearingTitle(bearing.bearing) }}
                </div>
              </li>
            </ul>
          </template>
        </template>
      </template>

      <v-alert v-if="error" type="error" class="mt-4">{{ error }}</v-alert>
    </v-card-text>
    <v-card-actions class="px-4 pb-4">
      <v-spacer />
      <template v-if="added === null">
        <v-btn variant="text" min-height="44" :disabled="sending" @click="emit('close')">Cancel</v-btn>
        <v-btn
          variant="outlined"
          color="primary"
          min-height="44"
          :disabled="sending || !text.trim() || tooLong"
          @click="send(true)"
        >
          Preview
        </v-btn>
        <v-btn color="primary" variant="flat" min-height="44" :disabled="sending || !canImport" @click="send(false)">
          Import
        </v-btn>
      </template>
      <v-btn v-else color="primary" variant="flat" min-height="44" @click="emit('close')">Close</v-btn>
    </v-card-actions>
  </v-card>
</template>

<style scoped>
.lines {
  list-style: none;
  padding: 0;
}
</style>
