<!--
  The upload dialog's card: one package (a zip or tar.gz), or a model file with or without its .json, sent with
  PUT /models/upload/{filename}, the .json first. A model file sent alone opens ModelFields, for what Frigate needs to
  know about it; a .json sent alone finishes a model file that's on the device already. Any file can be picked: a
  Frigate+ model file has no extension, and the device tells the kinds apart by name. Emits `uploaded` whenever a
  file reached the device, so the page lists it, and `close`.
-->
<script setup lang="ts">
import { ref } from 'vue'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import ModelFields from './ModelFields.vue'

type ModelOut = components['schemas']['ModelOut']

defineProps<{ detector: string | null }>()
const emit = defineEmits<{ uploaded: []; close: [] }>()

const files = ref<File[]>([])
const sending = ref(false)
const error = ref('')
const done = ref('')
const needsFields = ref<string | null>(null) // the model file's name, once it's on the device without a .json

const isArchive = (name: string) => ['.zip', '.tar.gz', '.tgz'].some((ending) => name.endsWith(ending))
const isSidecar = (name: string) => name.endsWith('.json')

// The files in the order they're sent, or why they can't be
function queue(chosen: File[]): File[] | string {
  const sidecar = chosen.find((file) => isSidecar(file.name))
  const others = chosen.filter((file) => file !== sidecar)
  if (sidecar && chosen.length === 1) return [sidecar]
  if (others.length !== 1 || others.some((file) => isSidecar(file.name)) || (sidecar && isArchive(others[0].name))) {
    return 'Choose one package, or one model file with or without its .json.'
  }
  if (!sidecar) return others
  if (sidecar.name !== `${others[0].name}.json`) return `The .json must be named for the model file: ${others[0].name}.json.`
  return [sidecar, others[0]]
}

async function upload() {
  error.value = ''
  done.value = ''
  const sends = queue(files.value)
  if (typeof sends === 'string') {
    error.value = sends
    return
  }
  sending.value = true
  let answer: ModelOut | undefined
  try {
    for (const file of sends) {
      const { data } = await api.PUT('/api/v1/models/upload/{filename}', {
        params: { path: { filename: file.name } },
        body: file as never, // the schema calls the body a string; the browser sends the file's bytes
        bodySerializer: (body: unknown) => body as BodyInit,
        headers: { 'Content-Type': 'application/octet-stream' },
      })
      answer = data
    }
    files.value = []
    const bare = sends.length === 1 && !isArchive(sends[0].name) && !isSidecar(sends[0].name)
    if (bare && !answer!.complete) needsFields.value = answer!.name
    else done.value = `Uploaded ${answer!.title}.`
  } catch (caught) {
    // A pair whose .json went through before its model file was refused: sending the pair again would be refused
    // for the .json, so say what finishes it
    const halfway = sends.length === 2 && answer !== undefined
    error.value = messageOf(caught) + (halfway ? ' Its .json is on the device: upload the model file on its own to finish it.' : '')
  } finally {
    sending.value = false
    if (answer) emit('uploaded')
  }
}

function saved(model: ModelOut) {
  needsFields.value = null
  done.value = `Uploaded ${model.title}.`
  emit('uploaded')
}
</script>

<template>
  <v-card color="surface" rounded="lg">
    <v-card-title class="text-h6 text-wrap pt-4">Upload a model</v-card-title>
    <v-card-text>
      <ModelFields v-if="needsFields" :name="needsFields" :detector="detector" @saved="saved" />
      <template v-else>
        <p class="text-body-1 mb-4">
          Choose the model's package, or its model file and .json. A model file on its own works too: you then fill
          in what Frigate needs to know about it.
        </p>
        <v-file-input
          v-model="files"
          label="Model files"
          multiple
          hint="A zip or tar.gz of the model file and its .json, not of a folder."
          persistent-hint
          variant="outlined"
          :disabled="sending"
        />
        <v-progress-linear v-if="sending" indeterminate color="primary" class="mt-4" />
      </template>
      <v-alert v-if="error" type="error" class="mt-4">{{ error }}</v-alert>
      <v-alert v-if="done" type="success" class="mt-4">{{ done }}</v-alert>
    </v-card-text>
    <v-card-actions class="px-4 pb-4">
      <v-spacer />
      <v-btn variant="text" min-height="44" @click="emit('close')">Close</v-btn>
      <v-btn
        v-if="!needsFields"
        color="primary"
        variant="flat"
        min-height="44"
        :loading="sending"
        :disabled="!files.length"
        @click="upload"
      >
        Upload
      </v-btn>
    </v-card-actions>
  </v-card>
</template>
