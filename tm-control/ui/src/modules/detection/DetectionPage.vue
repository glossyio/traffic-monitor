<!--
  The Detection page (GET /models): the detector, the model Frigate runs, the models on the device with their files,
  and the two label lists, for every logged-in user. Admins also get the Frigate+ API key's form, the
  frigate_plus_api_key row of GET /secrets, which the API refuses viewers.
-->
<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import EnteredSecret from '../../components/EnteredSecret.vue'
import { useSession } from '../../stores/session'
import LabelChips from './LabelChips.vue'

type ModelsState = components['schemas']['ModelsState']
type ModelOut = components['schemas']['ModelOut']
type ModelFile = components['schemas']['ModelFileOut']
type SecretState = components['schemas']['SecretState']

const session = useSession()
const route = useRoute()
const state = ref<ModelsState | null>(null)
const loadError = ref('')

async function load() {
  loadError.value = ''
  try {
    const { data } = await api.GET('/api/v1/models')
    state.value = data as ModelsState
  } catch (error) {
    loadError.value = messageOf(error)
  }
}

// The Frigate+ key (admins only), loaded again after each save or remove. The Status page's "Set the key" links to
// the section, and the page scrolls to it once the models have answered and the sections above it have their height.
const FRIGATE_PLUS_ID = 'frigate-plus'
const linkedToKey = route.hash === `#${FRIGATE_PLUS_ID}`
const secrets = ref<SecretState[] | null>(null)
const secretsError = ref('')
const key = computed(() => secrets.value?.find((secret) => secret.name === 'frigate_plus_api_key'))

async function loadSecrets() {
  secretsError.value = ''
  try {
    const { data } = await api.GET('/api/v1/secrets')
    secrets.value = data?.secrets ?? []
  } catch (error) {
    secretsError.value = messageOf(error)
  }
}

onMounted(async () => {
  if (session.isAdmin) void loadSecrets()
  await load()
  if (linkedToKey) {
    await nextTick() // the models are on the page now
    document.getElementById(FRIGATE_PLUS_ID)?.scrollIntoView?.() // jsdom, in the tests, has no scrollIntoView
  }
})

const detectorLine = computed(() => {
  const detector = state.value?.detector
  return detector ? `This device detects with ${detector}.` : "Frigate's detector is unknown."
})

const KINDS = {
  frigate_plus: 'a Frigate+ model',
  local: 'a local model',
  installer_default: "the installer's model",
}

const runningLine = computed(() => {
  if (!state.value) return ''
  const { running, models } = state.value
  if (!running.kind) return "What Frigate runs can't be told now."
  if (running.kind === 'frigate_default') return 'Frigate runs its built-in model.'
  const title = models.find((model) => model.running)?.title ?? running.name
  return `Frigate runs ${title}, ${KINDS[running.kind]}.`
})

// The sidecar's facts in one line, such as "trained 2026-10-01, yolo-generic, for edgetpu, 320×320"
function facts(model: ModelOut) {
  return [
    model.trained_at ? `trained ${model.trained_at.slice(0, 10)}` : null,
    model.type,
    model.detectors.length ? `for ${model.detectors.join(' or ')}` : null,
    model.width && model.height ? `${model.width}×${model.height}` : null,
  ]
    .filter(Boolean)
    .join(', ')
}

function mark(model: ModelOut) {
  if (model.running) return 'running'
  if (model.usable === false) return "can't run on this detector"
  if (!model.complete) return 'incomplete'
  return null
}

// Bytes in powers of 1024, as the Device page counts storage
function size(bytes: number) {
  if (bytes < 1024) return `${bytes} bytes`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

// A file's name, unless it's the model's title already (a file with no sidecar), and its size. The template adds
// the start of the hash, with the whole hash as the span's title.
function fileLine(model: ModelOut, file: ModelFile) {
  return file.name === model.title ? size(file.size) : `${file.name}, ${size(file.size)}`
}
</script>

<template>
  <div>
    <h1 class="text-h5 text-primary mb-6">Detection</h1>

    <v-alert v-if="loadError" type="error" class="mb-6">
      {{ loadError }}
      <template #append>
        <v-btn variant="text" @click="load">Try again</v-btn>
      </template>
    </v-alert>
    <v-progress-linear v-else-if="!state" indeterminate color="primary" />

    <template v-if="state">
      <section>
        <h2 class="text-h6 mb-2">Object detection</h2>
        <v-alert v-if="!state.frigate_answers" type="warning" class="mb-4">
          Frigate isn't answering; this is what its config file says.
        </v-alert>
        <p class="text-body-1">{{ detectorLine }}</p>
        <p class="text-body-1 mb-2">{{ runningLine }}</p>
        <v-list bg-color="transparent" class="py-0">
          <v-list-item v-for="model in state.models" :key="model.name" class="px-0 py-3">
            <div class="d-flex flex-wrap align-center ga-2">
              <span class="text-body-1 text-break">{{ model.title }}</span>
              <v-chip v-if="mark(model)" size="small" variant="outlined" :color="model.running ? 'primary' : undefined">
                {{ mark(model) }}
              </v-chip>
            </div>
            <div v-if="facts(model)" class="text-body-2 text-secondary">{{ facts(model) }}</div>
            <!-- On one line, so no space comes before the comma; the hash's start doesn't wrap away from "SHA-256" -->
            <div v-for="file in model.files" :key="file.name" class="text-body-2 text-secondary text-break">
              {{ fileLine(model, file) }}<template v-if="file.sha256">, <span class="text-no-wrap" :title="file.sha256">SHA-256 {{ file.sha256.slice(0, 12) }}</span></template>
            </div>
            <div v-if="model.problem" class="text-body-2">{{ model.problem }}</div>
          </v-list-item>
        </v-list>
      </section>

      <section class="mt-10">
        <h2 class="text-h6 mb-2">What the model recognises</h2>
        <p class="text-body-1 mb-4">Frigate tracks the objects in the second list that the model recognises.</p>
        <LabelChips v-if="state.labels.recognised" title="Recognises" :labels="state.labels.recognised" />
        <section v-else>
          <h3 class="text-subtitle-1 font-weight-medium mb-2">Recognises</h3>
          <p class="text-body-2 text-secondary">
            Frigate isn't answering, and the running model has no sidecar on the device.
          </p>
        </section>
        <LabelChips title="Tracked by this device" :labels="state.labels.tracked" class="mt-6" />
      </section>
    </template>

    <section :id="FRIGATE_PLUS_ID" class="mt-10 frigate-plus">
      <h2 class="text-h6 mb-2">Frigate+</h2>
      <p class="text-body-1 mb-2">
        When the device is online and has a Frigate+ API key, Frigate downloads a Frigate+ model itself: pick it in
        Frigate, under Settings, System, Detectors and model.
      </p>
      <p class="text-body-1 mb-6">
        When it's offline, download the model's two files from the Frigate+ website on another computer, then upload
        them on this page.
      </p>
      <template v-if="session.isAdmin">
        <v-alert v-if="secretsError" type="error">
          {{ secretsError }}
          <template #append>
            <v-btn variant="text" @click="loadSecrets">Try again</v-btn>
          </template>
        </v-alert>
        <v-progress-linear v-else-if="!secrets" indeterminate color="primary" />
        <EnteredSecret v-if="key" :secret="key" @changed="loadSecrets" />
      </template>
    </section>
  </div>
</template>

<style scoped>
/* Clear the app bar when the page scrolls to the section */
.frigate-plus {
  scroll-margin-top: 80px;
}
</style>
