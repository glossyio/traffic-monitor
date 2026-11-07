<!--
  One model on the Detection page, in a bordered block: its title and chip, its facts, one line per file, the API's
  problem, and for admins its buttons, the reason a Use can't work, and the result of its last action. The block for
  the model Frigate runs is tinted. A block the page makes for a default with no file on the device has no files.
  The page keeps the state and the actions; the buttons only emit.
-->
<script setup lang="ts">
import { computed } from 'vue'
import type { components } from '../../api/schema'
import ActionResult, { type Result } from './ActionResult.vue'

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
      <span class="text-body-1 text-break">{{ block.title }}</span>
      <v-chip v-if="mark" size="small" variant="outlined" :color="block.inUse ? 'primary' : undefined">
        {{ mark }}
      </v-chip>
    </div>
    <div v-if="block.facts" class="text-body-2 text-secondary">{{ block.facts }}</div>
    <template v-if="block.model">
      <!-- A file's name, its size, and the start of its hash, with the whole hash as the span's title. On one line, so
           no space comes before a comma. The name may break anywhere, so a long one (a Frigate+ model's 32 characters)
           never leaves its comma to start the next line; the hash's start doesn't wrap away from "SHA-256". -->
      <div v-for="file in block.model.files" :key="file.name" class="text-body-2 text-secondary text-break">
        <template v-if="named(block.model, file)"><span class="file-name">{{ file.name }}</span>, </template>{{ size(file.size) }}<template v-if="file.sha256">, <span class="text-no-wrap" :title="file.sha256">SHA-256 {{ file.sha256.slice(0, 12) }}</span></template>
      </div>
      <div v-if="block.model.problem" class="text-body-2">{{ block.model.problem }}</div>
    </template>
    <!-- The defaults have no package and can't be deleted; their Use puts back the device's default -->
    <template v-if="admin">
      <div v-if="canUse || canDownload || canDelete" class="d-flex flex-wrap ga-2 mt-2">
        <v-btn
          v-if="canUse"
          variant="outlined"
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
          color="primary"
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
  </div>
</template>

<style scoped>
.file-name {
  word-break: break-all;
}
</style>
