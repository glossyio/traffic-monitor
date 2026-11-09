<!--
  One model on the Detection page, in a bordered card: its title and chip, its facts, the API's problem, and for admins
  its buttons, the reason a Use can't work, and the result of its last action. Below those, a closed fold holds one line
  per file and, when the model's labels are known, its objects and any tracked objects it doesn't recognise. The card
  for the model Frigate runs is tinted. A block the page makes for a default with no file on the device has no fold.
  The page keeps the state and the actions; the buttons only emit.
-->
<script setup lang="ts">
import { computed } from 'vue'
import type { components } from '../../api/schema'
import ActionResult, { type Result } from './ActionResult.vue'
import LabelChips from './LabelChips.vue'

type ModelOut = components['schemas']['ModelOut']
type ModelFile = components['schemas']['ModelFileOut']

export interface Block {
  key: string // the model's name, or "#frigate_default" / "#installer_default" for a block the page makes
  title: string
  facts: string
  model: ModelOut | null // null for a block the page makes
  kind: ModelOut['kind']
  inUse: boolean
}

const props = defineProps<{
  block: Block
  admin: boolean
  busy: 'use' | 'download' | 'delete' | null // the action running on this block
  working: boolean // any action, or the wait for Frigate after a use
  result: Result | null
  useBlocked: string | null
  canUse: boolean
  tracked: string[] // what the device tracks, filled in the model's own list
  missing: string[] // tracked objects this model doesn't recognise
}>()
defineEmits<{ use: []; download: []; remove: [] }>()

const isDefault = computed(() => props.block.kind === 'installer_default' || props.block.kind === 'frigate_default')
const canDownload = computed(() => !isDefault.value && !!props.block.model?.complete)
const canDelete = computed(() => !isDefault.value && !!props.block.model?.deletable)

const mark = computed(() => {
  const { inUse, model } = props.block
  if (inUse) return 'In use'
  if (model?.usable === false) return "can't run on this detector"
  if (model && !model.complete) return 'incomplete'
  return null
})

const foldTitle = computed(() => (props.block.model?.labels ? 'Files and objects' : 'Files'))
const missingLine = computed(() => {
  const count = props.missing.length
  return `Doesn't recognise ${count} ${count === 1 ? 'object' : 'objects'} tracked on this device:`
})

// Bytes in powers of 1024, as the Device page counts storage
function size(bytes: number) {
  if (bytes < 1024) return `${bytes} bytes`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

// A file's name shows unless it's the model's title already (a file with no sidecar)
const named = (model: ModelOut, file: ModelFile) => file.name !== model.title
</script>

<template>
  <div class="model border rounded-lg pa-4" :class="{ 'bg-surface in-use': block.inUse }">
    <div class="d-flex flex-wrap align-center ga-2">
      <h3 class="text-body-1 text-break">{{ block.title }}</h3>
      <v-chip v-if="mark" size="small" variant="outlined" :color="block.inUse ? 'primary' : undefined">
        {{ mark }}
      </v-chip>
    </div>
    <div v-if="block.facts" class="text-body-2 text-secondary">{{ block.facts }}</div>
    <div v-if="block.model?.problem" class="text-body-2">{{ block.model.problem }}</div>
    <!-- The defaults have no package and can't be deleted; their Use puts back the device's default -->
    <template v-if="admin">
      <div v-if="canUse || canDownload || canDelete" class="d-flex flex-wrap ga-2 mt-2">
        <v-btn
          v-if="canUse"
          variant="flat"
          color="primary"
          min-height="44"
          :disabled="working || useBlocked !== null"
          :loading="busy === 'use'"
          @click="$emit('use')"
        >
          Use
        </v-btn>
        <v-btn
          v-if="canDownload"
          variant="outlined"
          color="primary"
          min-height="44"
          :disabled="working"
          :loading="busy === 'download'"
          @click="$emit('download')"
        >
          Download
        </v-btn>
        <v-btn
          v-if="canDelete"
          variant="outlined"
          color="error"
          min-height="44"
          :disabled="working"
          :loading="busy === 'delete'"
          @click="$emit('remove')"
        >
          Delete
        </v-btn>
      </div>
      <div v-if="canUse && useBlocked" class="text-body-2 text-secondary mt-1">{{ useBlocked }}</div>
    </template>
    <ActionResult v-if="result" :result="result" />
    <!-- Transparent, so the card in use keeps its tint. Static, so the title doesn't grow when it opens. Eager, so the
         page's height is known when a link scrolls to the key panel. -->
    <v-expansion-panels v-if="block.model" flat static bg-color="transparent" class="fold mt-1">
      <v-expansion-panel eager>
        <v-expansion-panel-title class="text-body-2">{{ foldTitle }}</v-expansion-panel-title>
        <v-expansion-panel-text>
          <!-- A file's name, its size, and the start of its hash, with the whole hash as the span's title. On one line,
               so no space comes before a comma. The name may break anywhere, so a long one (a Frigate+ model's 32
               characters) never leaves its comma to start the next line; the hash's start doesn't wrap away from
               "SHA-256". -->
          <div v-for="file in block.model.files" :key="file.name" class="text-body-2 text-secondary text-break">
            <template v-if="named(block.model, file)"><span class="file-name">{{ file.name }}</span>, </template>{{ size(file.size) }}<template v-if="file.sha256">, <span class="text-no-wrap" :title="file.sha256">SHA-256 {{ file.sha256.slice(0, 12) }}</span></template>
          </div>
          <template v-if="block.model.labels">
            <LabelChips
              class="mt-3"
              :title="`Objects it recognises (${block.model.labels.length})`"
              :labels="block.model.labels"
              :marked="tracked"
              marked-legend="Filled: tracked on this device."
            />
            <template v-if="missing.length">
              <p class="text-body-2 mt-3 mb-2">{{ missingLine }}</p>
              <div class="d-flex flex-wrap ga-2">
                <v-chip v-for="label in missing" :key="label" size="small" variant="outlined" color="warning">
                  {{ label }}
                </v-chip>
              </div>
            </template>
          </template>
        </v-expansion-panel-text>
      </v-expansion-panel>
    </v-expansion-panels>
  </div>
</template>

<style scoped>
.file-name {
  word-break: break-all;
}

/* The fold's title and content line up with the card's other text */
.fold :deep(.v-expansion-panel-title) {
  padding-inline: 0;
}

.fold :deep(.v-expansion-panel-text__wrapper) {
  padding: 0 0 8px;
}
</style>
