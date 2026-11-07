<!--
  The Detection page (GET /models): the detector, the model Frigate runs, the models on the device with their files,
  and the two label lists, for every logged-in user. Admins also get the actions (upload, use, download, delete) and
  the Frigate+ API key's form, the frigate_plus_api_key row of GET /secrets, which the API refuses viewers.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { saveBlob } from '../../components/download'
import EnteredSecret from '../../components/EnteredSecret.vue'
import { useSession } from '../../stores/session'
import ActionResult, { type Result } from './ActionResult.vue'
import LabelChips from './LabelChips.vue'
import UploadModel from './UploadModel.vue'

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
}

const runningLine = computed(() => {
  if (!state.value) return ''
  const { running, models } = state.value
  if (!running.kind) return "Frigate's model is unknown."
  if (running.kind === 'frigate_default') return 'Frigate runs its built-in model.'
  if (running.kind === 'installer_default') return "Frigate runs the installer's model."
  const title = models.find((model) => model.running)?.title ?? running.name
  return title ? `Frigate runs ${title}, ${KINDS[running.kind]}.` : `Frigate runs ${KINDS[running.kind]}.`
})

// The installer's model has no sidecar, so the API's title for it is its file name, which goes on the facts line
const INSTALLERS = "The installer's model"
const titleOf = (model: ModelOut) => (model.kind === 'installer_default' ? INSTALLERS : model.title)

// The sidecar's facts in one line, such as "trained 2026-10-01, yolo-generic, for edgetpu, 320×320"
function facts(model: ModelOut) {
  if (model.kind === 'installer_default') return model.name
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

// The admin's actions. One runs at a time; `busy` names it ("use mine.tflite"), and `restarting` is true while the
// page waits for Frigate after a use. Each result shows where its action was: under the model, under the default's
// button (DEFAULT), or above the list (LIST) for a model that's gone.
const DEFAULT = 'default'
const LIST = 'list'
const busy = ref<string | null>(null)
const restarting = ref(false)
const working = computed(() => busy.value !== null || restarting.value)
const result = ref<(Result & { at: string }) | null>(null)

// What POST /models/default/use would put back here, offered when Frigate runs something else
const defaultOffer = computed(() => {
  if (!state.value) return null
  const { default: fallback, running } = state.value
  if (fallback === 'installer_default' && running.kind !== 'installer_default') {
    return { title: "the installer's model", label: "Use the installer's model" }
  }
  if (fallback === 'frigate_default' && running.kind !== 'frigate_default') {
    return { title: "Frigate's built-in model", label: "Use Frigate's built-in model" }
  }
  return null
})

function useBlocked(model: ModelOut) {
  if (!model.complete) return 'It can be used once it has both its model file and its .json.'
  if (model.usable !== false) return null
  const built = model.detectors.length ? `It's built for ${model.detectors.join(' or ')}` : 'Its .json names no detector'
  return `${built}, and this device detects with ${state.value?.detector}.`
}

// The confirmation: a use or a delete of a model, or a use of the default (model null)
const CONFIRM = {
  use: { verb: 'Use', text: "Frigate restarts, which takes about a minute. Traffic isn't counted while it does." },
  delete: { verb: 'Delete', text: "Both of its files are removed from the device. This can't be undone." },
}
const confirming = ref<{ action: 'use' | 'delete'; title: string; model: ModelOut | null } | null>(null)
const confirmOpen = computed({
  get: () => confirming.value !== null,
  set: (open: boolean) => {
    if (!open) confirming.value = null
  },
})

function confirmed() {
  const { action, model } = confirming.value!
  if (action === 'delete') void remove(model!)
  else void use(model)
}

// Use a model, or the default, then ask GET /models every 3 seconds until Frigate answers with it, for 90 seconds
const POLL_EVERY = 3000
const POLL_FOR = 90_000
let pollTimer: ReturnType<typeof setTimeout> | undefined
let left = false
onBeforeUnmount(() => {
  left = true
  clearTimeout(pollTimer)
})

async function use(model: ModelOut | null) {
  const at = model?.name ?? DEFAULT
  const fallback = state.value?.default
  result.value = null
  busy.value = `use ${at}`
  try {
    if (model) await api.POST('/api/v1/models/{name}/use', { params: { path: { name: model.name } } })
    else await api.POST('/api/v1/models/default/use')
  } catch (error) {
    result.value = { at, type: 'error', text: messageOf(error) }
    return
  } finally {
    busy.value = null
  }
  result.value = { at, type: 'info', text: 'Frigate is restarting.' }
  restarting.value = true
  const runs = (answer: ModelsState) =>
    answer.frigate_answers && (model ? answer.running.name === model.name : answer.running.kind === fallback)
  const done = model
    ? `Frigate runs ${titleOf(model)}.`
    : `Frigate runs ${fallback === 'installer_default' ? "the installer's model" : 'its built-in model'}.`
  poll(at, runs, done, Date.now())
}

function poll(at: string, runs: (answer: ModelsState) => boolean, done: string, started: number) {
  pollTimer = setTimeout(async () => {
    try {
      const { data } = await api.GET('/api/v1/models')
      state.value = data as ModelsState
    } catch {
      // the device may be busy; the next poll asks again
    }
    if (left) return
    if (state.value && runs(state.value)) {
      result.value = { at, type: 'success', text: done }
    } else if (Date.now() - started >= POLL_FOR) {
      result.value = { at, type: 'warning', text: '', stalled: true }
    } else {
      return poll(at, runs, done, started)
    }
    restarting.value = false
  }, POLL_EVERY)
}

async function download(model: ModelOut) {
  result.value = null
  busy.value = `download ${model.name}`
  try {
    const { data } = await api.GET('/api/v1/models/{name}/package', {
      params: { path: { name: model.name } },
      parseAs: 'blob',
    })
    saveBlob(data as Blob, `${model.name}.zip`)
  } catch (error) {
    result.value = { at: model.name, type: 'error', text: messageOf(error) }
  } finally {
    busy.value = null
  }
}

async function remove(model: ModelOut) {
  result.value = null
  busy.value = `delete ${model.name}`
  try {
    await api.DELETE('/api/v1/models/{name}', { params: { path: { name: model.name } } })
    await load()
    result.value = { at: LIST, type: 'success', text: `Deleted ${titleOf(model)}.` }
  } catch (error) {
    result.value = { at: model.name, type: 'error', text: messageOf(error) }
  } finally {
    busy.value = null
  }
}

// The upload dialog, with a new card each time it opens
const uploadOpen = ref(false)
const uploads = ref(0)

function openUpload() {
  result.value = null
  uploads.value += 1
  uploadOpen.value = true
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
        <v-btn
          v-if="session.isAdmin"
          variant="outlined"
          color="primary"
          size="large"
          class="my-2"
          :disabled="working"
          @click="openUpload"
        >
          Upload a model
        </v-btn>
        <ActionResult v-if="result?.at === LIST" :result="result" />
        <v-list bg-color="transparent" class="py-0">
          <v-list-item v-for="model in state.models" :key="model.name" class="px-0 py-3">
            <div class="d-flex flex-wrap align-center ga-2">
              <span class="text-body-1 text-break">{{ titleOf(model) }}</span>
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
            <!-- The installer's model has none of these: the button under the list uses it, and it has no package -->
            <template v-if="session.isAdmin && model.kind !== 'installer_default'">
              <div class="d-flex flex-wrap ga-2 mt-2">
                <v-btn
                  v-if="!model.running"
                  variant="outlined"
                  color="primary"
                  min-height="44"
                  :disabled="working || useBlocked(model) !== null"
                  :loading="busy === `use ${model.name}`"
                  @click="confirming = { action: 'use', title: titleOf(model), model }"
                >
                  Use
                </v-btn>
                <v-btn
                  v-if="model.complete"
                  variant="outlined"
                  color="primary"
                  min-height="44"
                  :disabled="working"
                  :loading="busy === `download ${model.name}`"
                  @click="download(model)"
                >
                  Download
                </v-btn>
                <v-btn
                  v-if="model.deletable"
                  variant="outlined"
                  color="primary"
                  min-height="44"
                  :disabled="working"
                  :loading="busy === `delete ${model.name}`"
                  @click="confirming = { action: 'delete', title: titleOf(model), model }"
                >
                  Delete
                </v-btn>
              </div>
              <div v-if="!model.running && useBlocked(model)" class="text-body-2 text-secondary mt-1">
                {{ useBlocked(model) }}
              </div>
            </template>
            <ActionResult v-if="result?.at === model.name" :result="result" />
          </v-list-item>
        </v-list>
        <div v-if="session.isAdmin && (defaultOffer || result?.at === DEFAULT)" class="mt-2">
          <v-btn
            v-if="defaultOffer"
            variant="outlined"
            color="primary"
            size="large"
            :disabled="working"
            :loading="busy === `use ${DEFAULT}`"
            @click="confirming = { action: 'use', title: defaultOffer.title, model: null }"
          >
            {{ defaultOffer.label }}
          </v-btn>
          <ActionResult v-if="result?.at === DEFAULT" :result="result" />
        </div>
      </section>

      <section class="mt-10">
        <h2 class="text-h6 mb-2">What the model recognises</h2>
        <p class="text-body-1 mb-4">Frigate tracks only the objects that are in both lists.</p>
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
        When the device is online and has a Frigate+ API key, pick a Frigate+ model in Frigate, under Settings,
        System, Detectors and model, and Frigate downloads it.
      </p>
      <p class="text-body-1 mb-6">
        When it's offline, an administrator can upload the model's two files on this page, as a package from whoever
        trained the model or copied from another device's Frigate.
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

    <v-dialog v-model="uploadOpen" max-width="560">
      <UploadModel :key="uploads" :detector="state?.detector ?? null" @uploaded="load" @close="uploadOpen = false" />
    </v-dialog>
    <ConfirmDialog
      v-model="confirmOpen"
      :title="confirming ? `${CONFIRM[confirming.action].verb} ${confirming.title}?` : ''"
      :text="confirming ? CONFIRM[confirming.action].text : ''"
      :confirm-text="confirming ? CONFIRM[confirming.action].verb : ''"
      @confirm="confirmed"
    />
  </div>
</template>

<style scoped>
/* Clear the app bar when the page scrolls to the section */
.frigate-plus {
  scroll-margin-top: 80px;
}
</style>
