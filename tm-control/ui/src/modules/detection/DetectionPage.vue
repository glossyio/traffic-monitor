<!--
  The Detection page (GET /models), in four sections, for every logged-in user: Object detection (the detector, the
  running model, and what is wrong with Frigate's answer), Model in use (one card, which holds the running model's two
  object lists), Frigate+, and Other models on this device. The card in use always exists once the models have loaded:
  a model with no entry in the list, or one that can't be read, gets a card the page makes. The Frigate+ section does
  not wait for the models, so it shows when they can't load. Admins also get the actions (upload, use, download,
  delete) and, in the Frigate+ section, two panels: the API key's, the frigate_plus_api_key row of GET /secrets, which
  the API refuses viewers, and the form that uses a Frigate+ model by its ID. Frigate downloads a model for minutes
  at a time, so the page follows the fetch record GET /models carries for admins, which it shows to anyone who opens
  the page meanwhile.
-->
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { saveBlob } from '../../components/download'
import EnteredSecret from '../../components/EnteredSecret.vue'
import { useSession } from '../../stores/session'
import ActionResult, { type Result } from './ActionResult.vue'
import ModelBlock, { type Block } from './ModelBlock.vue'
import PlusModelById from './PlusModelById.vue'
import UploadModel from './UploadModel.vue'

type ModelsState = components['schemas']['ModelsState']
type ModelOut = components['schemas']['ModelOut']
type DefaultKind = NonNullable<ModelsState['default']>
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
// the section, which is always there, and "Choose a model" to the section with the ID panel; the linked panel opens,
// and the page scrolls to the section once the models have answered and the sections above it have their height.
const FRIGATE_PLUS_ID = 'frigate-plus'
const MODEL_PANEL = 'frigate-plus-model'
const linked = [FRIGATE_PLUS_ID, MODEL_PANEL].filter((name) => route.hash === `#${name}`)
const secrets = ref<SecretState[] | null>(null)
const secretsError = ref('')
const key = computed(() => secrets.value?.find((secret) => secret.name === 'frigate_plus_api_key'))
const panelsOpen = ref<string[]>([...linked])

// The key's state beside the panel's title "API key", which a closed panel still shows: nothing for a viewer or until
// the secrets answer, and "in use" only while Frigate runs a Frigate+ model
const keyState = computed(() => {
  if (!key.value) return ''
  if (!key.value.set) return 'not set'
  const set = key.value.ends_with ? `set, ending in ${key.value.ends_with}` : 'set'
  return state.value?.running.kind === 'frigate_plus' ? `${set}, in use` : set
})

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
  if (linked.length) {
    await nextTick() // the models are on the page now
    document.getElementById(FRIGATE_PLUS_ID)?.scrollIntoView?.() // jsdom, in the tests, has no scrollIntoView
  }
})

// The two facts at the top, as the Device page's Software grid has them
const detectorValue = computed(() => state.value?.detector ?? 'Unknown')

const KINDS = {
  frigate_plus: 'a Frigate+ model',
  local: 'a local model',
}
const KIND_FACTS = {
  frigate_plus: 'Frigate+ model',
  local: 'Local model',
}

// The two defaults have no sidecar, so the API's title for each is its file name, which goes on the facts line
const DEFAULT_TITLES: Record<DefaultKind, string> = {
  installer_default: "The installer's model",
  frigate_default: "Frigate's built-in model",
}
// A default the API can't list (no file in model_cache) still gets a block, with this as its facts line
const MADE_FACTS: Record<DefaultKind, string> = {
  installer_default: 'Set up by the installer.',
  frigate_default: 'Built into Frigate.',
}
const isDefaultKind = (kind: ModelOut['kind'] | null): kind is DefaultKind =>
  kind === 'installer_default' || kind === 'frigate_default'
const titleOf = (model: ModelOut) => (isDefaultKind(model.kind) ? DEFAULT_TITLES[model.kind] : model.title)

const runningValue = computed(() => {
  if (!state.value) return ''
  const { running, models } = state.value
  if (!running.kind) return 'Unknown'
  if (isDefaultKind(running.kind)) return DEFAULT_TITLES[running.kind]
  const kind = KINDS[running.kind]
  const title = models.find((model) => model.running)?.title ?? running.name
  return title ? `${title}, ${kind}` : kind.charAt(0).toUpperCase() + kind.slice(1)
})

// The kind and the sidecar's facts in one line, such as "Local model, trained 2026-10-01, yolo-generic, for edgetpu,
// 320×320"
function facts(model: ModelOut) {
  if (isDefaultKind(model.kind)) return model.name
  return [
    KIND_FACTS[model.kind],
    model.trained_at ? `trained ${model.trained_at.slice(0, 10)}` : null,
    model.type,
    model.detectors.length ? `for ${model.detectors.join(' or ')}` : null,
    model.width && model.height ? `${model.width}×${model.height}` : null,
  ]
    .filter(Boolean)
    .join(', ')
}

// One card per model: the one Frigate runs under "Model in use", the rest under "Other models". A default with no file
// on the device gets a block the page makes (model null), keyed "#<kind>", which no model's name can be. So does a
// running model with no entry in the list, keyed RUNNING.
const RUNNING = '#running'
function listed(model: ModelOut): Block {
  return { key: model.name, title: titleOf(model), facts: facts(model), model, kind: model.kind, inUse: model.running }
}
function made(kind: DefaultKind, inUse: boolean): Block {
  return { key: `#${kind}`, title: DEFAULT_TITLES[kind], facts: MADE_FACTS[kind], model: null, kind, inUse }
}

// The card in use: the running model's entry, else a default's block, else a block for what Frigate's config names, or
// for a model that can't be read
const inUse = computed<Block | null>(() => {
  if (!state.value) return null
  const { running, models } = state.value
  const model = models.find((m) => m.running)
  if (model) return listed(model)
  if (isDefaultKind(running.kind)) return made(running.kind, true)
  return {
    key: RUNNING,
    title: running.name ?? 'Unknown model',
    facts: running.name
      ? "Named in Frigate's config; its files aren't on this device."
      : "Frigate's model couldn't be read.",
    model: null,
    kind: running.kind,
    inUse: true,
  }
})

const others = computed<Block[]>(() => {
  if (!state.value) return []
  const { default: fallback, running, models } = state.value
  const blocks = models.filter((model) => model.name !== inUse.value?.key).map(listed)
  if (fallback && running.kind !== fallback && !models.some((model) => model.kind === fallback)) {
    blocks.push(made(fallback, false))
  }
  return blocks
})

// Frigate's list against the .json of the model in use, as sets
const listsDiffer = computed(() => {
  const { recognised, source } = state.value?.labels ?? {}
  const own = inUse.value?.model?.labels
  if (source !== 'frigate' || !recognised || !own) return false
  const [reported, ours] = [new Set(recognised), new Set(own)]
  return reported.size !== ours.size || [...reported].some((label) => !ours.has(label))
})

// The admin's actions. One runs at a time; `busy` names it ("use mine.tflite"), and `restarting` is true while the
// page waits for Frigate after a use. Each result shows where its action was: under the model, under the default's
// button (DEFAULT), or above the list (LIST) for a model that's gone. A model's name can't start with "#".
const DEFAULT = '#default'
const LIST = '#list'
const PLUS = '#plus' // the ID form's result
const busy = ref<string | null>(null)
const restarting = ref(false)
const working = computed(() => busy.value !== null || restarting.value || state.value?.fetch?.state === 'downloading')
const result = ref<(Result & { at: string }) | null>(null)

// A default's block offers what POST /models/default/use puts back, when Frigate runs something else
function canUseDefault(block: Block) {
  const { default: fallback, running } = state.value!
  return block.kind === fallback && running.kind !== fallback && !block.inUse
}

function useBlocked(model: ModelOut) {
  if (!model.complete) return 'It can be used once it has both its model file and its .json.'
  if (model.usable !== false) return null
  const built = model.detectors.length ? `It's built for ${model.detectors.join(' or ')}` : 'Its .json names no detector'
  return `${built}, and this device detects with ${state.value?.detector}.`
}

// The tracked objects a switch to this block's model would lose: none for the model in use, or when its labels aren't
// known
function missingFrom(block: Block) {
  const labels = block.model?.labels
  if (!labels || block.inUse) return []
  return (state.value?.labels.tracked ?? []).filter((label) => !labels.includes(label))
}

// What ModelBlock needs of the page's state for one block. A use of the default shows its result at DEFAULT, on the
// block of the default this device would get, so the result follows the block when it moves under "Model in use".
// Any other result is at its block's key.
function blockProps(block: Block) {
  const at = block.kind && block.kind === state.value?.default ? DEFAULT : block.key
  const on = (action: string) => busy.value === `${action} ${action === 'use' ? at : block.key}`
  const here = result.value?.at === at || result.value?.at === block.key
  return {
    block,
    lists: block.inUse
      ? { labels: state.value!.labels, listsDiffer: listsDiffer.value, frigateAnswers: state.value!.frigate_answers }
      : null,
    admin: session.isAdmin,
    busy: on('use') ? 'use' : on('download') ? 'download' : on('delete') ? 'delete' : null,
    working: working.value,
    result: here ? result.value : null,
    useBlocked: block.model && !isDefaultKind(block.kind) ? useBlocked(block.model) : null,
    canUse: isDefaultKind(block.kind) ? canUseDefault(block) : !block.inUse,
    tracked: state.value?.labels.tracked ?? [],
    missing: missingFrom(block),
  } as const
}

// A default's title inside a sentence
const asked = (block: Block) =>
  block.kind === 'installer_default' ? "the installer's model" : "Frigate's built-in model"

function askToUse(block: Block) {
  if (block.model && !isDefaultKind(block.kind)) {
    confirming.value = { action: 'use', title: block.title, model: block.model }
  } else {
    confirming.value = { action: 'use', title: asked(block), model: null }
  }
}

// A model with both its files downloads as a package. Any other downloads as its model file alone, once the operator
// has read what an upload of that file will need. A default's file can't be uploaded under its own name, which every
// device keeps for its own copy.
const packaged = (model: ModelOut) => model.complete && !isDefaultKind(model.kind)

function askToDownload(block: Block) {
  const model = block.model!
  if (packaged(model)) void download(model)
  else if (isDefaultKind(block.kind)) confirming.value = { action: 'downloadDefault', title: asked(block), model }
  else confirming.value = { action: 'download', title: block.title, model }
}

// The confirmation: a use or a delete of a model, a use of the default (model null), or a download of a model file
// alone
const FILLS_IN = 'fills in what Frigate needs to know about it.'
const CONFIRM = {
  use: { verb: 'Use', text: "Frigate restarts, which takes about a minute. Traffic isn't counted while it does." },
  delete: { verb: 'Delete', text: "Both of its files are removed from the device. This can't be undone." },
  // The ID form's: its title is the ID, which the confirmation names. An ID of a model the device has, with both its
  // files, is confirmed as a use instead (`asked` in `askToUsePlus`; the request is the same)
  plus: {
    verb: 'Download and use',
    text:
      'Frigate downloads the model, then restarts. The download can take a few minutes, and the restart about one. ' +
      "Traffic isn't counted while Frigate restarts.",
  },
  download: {
    verb: 'Download',
    text:
      'It has no .json the device can read, so the download is the model file alone. Whoever uploads the file ' +
      FILLS_IN,
  },
  downloadDefault: {
    verb: 'Download',
    text:
      'It has no .json, so the download is the model file alone. A device keeps this file name for its own copy, ' +
      `so rename the file before uploading it. Whoever uploads it ${FILLS_IN}`,
  },
}
type Action = keyof typeof CONFIRM
const confirming = ref<{ action: Action; title: string; model: ModelOut | null } | null>(null)

// The ID form's confirmation: a model on the device with both its files is a Use, so the page confirms it as one, with
// the model's title, and the server takes the short path. Any other ID, or models not loaded yet, is a download.
function askToUsePlus(id: string) {
  const model = state.value?.models.find((m) => m.name === id && m.complete) ?? null
  confirming.value = { action: 'plus', title: id, model }
}

// What the dialog shows: the action's own words, but a plus action with a model is Use's, titled by the model
const shown = computed(() => {
  if (!confirming.value) return null
  const { action, title, model } = confirming.value
  const same = action === 'plus' && model
  const words = CONFIRM[same ? 'use' : action]
  return { ...words, title: same ? titleOf(model) : title }
})
const confirmOpen = computed({
  get: () => confirming.value !== null,
  set: (open: boolean) => {
    if (!open) confirming.value = null
  },
})

function confirmed() {
  const { action, model, title } = confirming.value!
  if (action === 'delete') void remove(model!)
  else if (action === 'use') void use(model)
  else if (action === 'plus') void usePlus(title)
  else void download(model!)
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

function poll(
  at: string,
  runs: (answer: ModelsState) => boolean,
  done: string | ((answer: ModelsState) => string),
  started: number,
) {
  pollTimer = setTimeout(async () => {
    try {
      const { data } = await api.GET('/api/v1/models')
      state.value = data as ModelsState
    } catch {
      // the device may be busy; the next poll asks again
    }
    if (left) return
    if (state.value && runs(state.value)) {
      result.value = { at, type: 'success', text: typeof done === 'function' ? done(state.value) : done }
    } else if (Date.now() - started >= POLL_FOR) {
      result.value = { at, type: 'warning', text: '', stalled: true }
    } else {
      return poll(at, runs, done, started)
    }
    restarting.value = false
  }, POLL_EVERY)
}

// Use a Frigate+ model by its ID. A model the device has is a use. Any other is downloaded by Frigate first: the page
// puts up the download's record at once, which the watcher below follows with GET /models until the server ends it.
const plusForms = ref(0) // a new form each time the ID went through, so it starts empty
async function usePlus(id: string) {
  result.value = null
  busy.value = `use ${PLUS}`
  let started: 'restart' | 'download'
  try {
    const { data } = await api.POST('/api/v1/models/plus/{model_id}/use', { params: { path: { model_id: id } } })
    started = data!.started
  } catch (error) {
    result.value = { at: PLUS, type: 'error', text: messageOf(error) }
    return
  } finally {
    busy.value = null
  }
  if (started === 'download') {
    if (state.value) state.value.fetch = { model_id: id, state: 'downloading', message: null }
  } else {
    plusForms.value += 1
    waitFor(id)
  }
}

// Wait for Frigate to run the model with this ID, as after a use
function waitFor(id: string) {
  result.value = { at: PLUS, type: 'info', text: 'Frigate is restarting.' }
  restarting.value = true
  const titled = (answer: ModelsState) => answer.models.find((model) => model.name === id)?.title ?? id
  const runs = (answer: ModelsState) => answer.frigate_answers && answer.running.name === id
  poll(PLUS, runs, (answer) => `Frigate runs ${titled(answer)}.`, Date.now())
}

let fetchTimer: ReturnType<typeof setTimeout> | undefined
onBeforeUnmount(() => clearTimeout(fetchTimer))

// While a download runs, ask GET /models every 3 seconds, with no limit of the page's own: the server ends the record
function followDownload() {
  clearTimeout(fetchTimer)
  fetchTimer = setTimeout(async () => {
    try {
      const { data } = await api.GET('/api/v1/models')
      state.value = data as ModelsState
    } catch {
      // the device may be busy; the next poll asks again
    }
    if (!left && state.value?.fetch?.state === 'downloading') followDownload()
  }, POLL_EVERY)
}

// The page's one watcher on the fetch record: a download starts the polling and opens the panel; its end either
// restarts Frigate, which the page then waits for, or shows why it didn't. A refusal found on opening the page shows
// too, but a download that finished before then shows nothing.
watch(
  () => state.value?.fetch?.state,
  (now, before) => {
    const fetched = state.value?.fetch
    if (!fetched) return
    const open = () => {
      if (!panelsOpen.value.includes(MODEL_PANEL)) panelsOpen.value = [...panelsOpen.value, MODEL_PANEL]
    }
    if (now === 'downloading') {
      open()
      followDownload()
    } else if (now === 'saved') {
      if (before !== 'downloading') return
      plusForms.value += 1
      waitFor(fetched.model_id)
    } else if (before === 'downloading' || before === undefined) {
      open()
      result.value = { at: PLUS, type: 'error', text: fetched.message ?? 'Frigate could not download the model.' }
    }
  },
)

async function download(model: ModelOut) {
  result.value = null
  busy.value = `download ${model.name}`
  try {
    const whole = packaged(model)
    const { data } = await api.GET(whole ? '/api/v1/models/{name}/package' : '/api/v1/models/{name}/file', {
      params: { path: { name: model.name } },
      parseAs: 'blob',
    })
    saveBlob(data as Blob, whole ? `${model.name}.zip` : model.name)
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
    <h1 class="text-h5 text-primary mb-2">Detection</h1>
    <p class="text-body-1 mb-6">
      See which model Frigate detects objects with and what it recognises. Administrators can switch models and set
      the Frigate+ API key.
    </p>

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
        <!-- In safe mode Frigate runs a stand-in config, so the API reads the file instead; a Use goes through
             Frigate, which checks the whole config and restarts out of safe mode when it can run it -->
        <v-alert v-else-if="state.frigate_safe_mode" type="warning" class="mb-4">
          Frigate couldn't use its config and started in safe mode, so nothing is detected; this is what the config
          file says. Use a model to give Frigate a config it can run.
        </v-alert>
        <v-row dense class="facts mb-4">
          <v-col cols="6" sm="4">
            <div class="text-body-2 text-secondary">Detector</div>
            <div class="text-body-1 text-break">{{ detectorValue }}</div>
          </v-col>
          <v-col cols="6" sm="4">
            <div class="text-body-2 text-secondary">Running model</div>
            <div class="text-body-1 text-break">{{ runningValue }}</div>
          </v-col>
        </v-row>
      </section>

      <section v-if="inUse" class="mt-10">
        <h2 class="text-h6 mb-2">Model in use</h2>
        <ModelBlock
          v-bind="blockProps(inUse)"
          @use="askToUse(inUse)"
          @download="askToDownload(inUse)"
          @remove="confirming = { action: 'delete', title: inUse.title, model: inUse.model }"
        />
      </section>
    </template>

    <!-- Frigate+ sits above the other models and doesn't wait for them. The admin's key is one panel, its title
         "API key" with the key's state beside it -->
    <section :id="FRIGATE_PLUS_ID" class="mt-10 frigate-plus">
      <h2 class="text-h6 mb-2">Frigate+</h2>
      <p class="text-body-1 mb-2">
        When the device is online and has a Frigate+ API key, an administrator can use a model by its ID below, or pick
        one in Frigate, under Settings, System, Detectors and model.
      </p>
      <p class="text-body-1" :class="{ 'mb-4': session.isAdmin }">
        When it's offline, an administrator can upload the model's two files on this page, as a package from whoever
        trained the model or copied from another device's Frigate.
      </p>
      <v-expansion-panels v-if="session.isAdmin" v-model="panelsOpen" multiple flat bg-color="background">
        <v-expansion-panel :value="FRIGATE_PLUS_ID" class="border" eager>
          <h3 class="text-body-1">
            <v-expansion-panel-title>
              <span class="d-flex flex-wrap align-baseline key-title">
                <span class="text-subtitle-1 font-weight-medium">API key{{ ' ' }}</span>
                <span v-if="keyState" class="text-body-2 text-secondary">{{ keyState }}</span>
              </span>
            </v-expansion-panel-title>
          </h3>
          <v-expansion-panel-text>
            <v-alert v-if="secretsError" type="error">
              {{ secretsError }}
              <template #append>
                <v-btn variant="text" @click="loadSecrets">Try again</v-btn>
              </template>
            </v-alert>
            <v-progress-linear v-else-if="!secrets" indeterminate color="primary" />
            <EnteredSecret v-if="key" :secret="key" hide-title @changed="loadSecrets" />
          </v-expansion-panel-text>
        </v-expansion-panel>
        <v-expansion-panel :value="MODEL_PANEL" class="border" eager>
          <h3 class="text-body-1">
            <v-expansion-panel-title>
              <span class="text-subtitle-1 font-weight-medium">Use a model by its ID</span>
            </v-expansion-panel-title>
          </h3>
          <v-expansion-panel-text>
            <PlusModelById
              :key="plusForms"
              :disabled="working"
              :downloading="state?.fetch?.state === 'downloading'"
              :result="result?.at === PLUS ? result : null"
              @use="askToUsePlus"
            />
          </v-expansion-panel-text>
        </v-expansion-panel>
      </v-expansion-panels>
    </section>

    <template v-if="state">
      <section class="mt-10">
        <h2 class="text-h6 mb-2">Other models on this device ({{ others.length }})</h2>
        <v-btn
          v-if="session.isAdmin"
          variant="outlined"
          color="primary"
          size="large"
          :disabled="working"
          @click="openUpload"
        >
          Upload a model
        </v-btn>
        <ActionResult v-if="result?.at === LIST" :result="result" />
        <div v-if="others.length" class="d-flex flex-column ga-3 mt-4">
          <ModelBlock
            v-for="block in others"
            :key="block.key"
            v-bind="blockProps(block)"
            @use="askToUse(block)"
            @download="askToDownload(block)"
            @remove="confirming = { action: 'delete', title: block.title, model: block.model }"
          />
        </div>
        <p v-else class="text-body-2 text-secondary mt-4">No other models on this device.</p>
      </section>
    </template>

    <v-dialog v-model="uploadOpen" max-width="560">
      <UploadModel :key="uploads" :detector="state?.detector ?? null" @uploaded="load" @close="uploadOpen = false" />
    </v-dialog>
    <ConfirmDialog
      v-model="confirmOpen"
      :title="shown ? `${shown.verb} ${shown.title}?` : ''"
      :text="shown?.text ?? ''"
      :confirm-text="shown?.verb ?? ''"
      :confirm-color="shown?.verb === 'Download' ? 'primary' : undefined"
      @confirm="confirmed"
    />
  </div>
</template>

<style scoped>
/* Clear the app bar when the page scrolls to the section */
.frigate-plus {
  scroll-margin-top: 80px;
}

/* The key's state beside its name, or under it when the title wraps (Vuetify 3.13 has no column-gap class) */
.key-title {
  column-gap: 12px;
}
</style>
