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
import ModelBlock, { type Block } from './ModelBlock.vue'
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
// the section, which opens, and the page scrolls to it once the models have answered and the sections above it have
// their height.
const FRIGATE_PLUS_ID = 'frigate-plus'
const linkedToKey = route.hash === `#${FRIGATE_PLUS_ID}`
const secrets = ref<SecretState[] | null>(null)
const secretsError = ref('')
const key = computed(() => secrets.value?.find((secret) => secret.name === 'frigate_plus_api_key'))
const keyOpen = ref<string[]>(linkedToKey ? [FRIGATE_PLUS_ID] : [])

// The key's state for the panel's title, which a closed panel still shows: nothing for a viewer or until the
// secrets answer, and "in use" only while Frigate runs a Frigate+ model
const keyState = computed(() => {
  if (!key.value) return ''
  if (!key.value.set) return 'Not set'
  const set = key.value.ends_with ? `Set, ending in ${key.value.ends_with}` : 'Set'
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
  if (linkedToKey) {
    await nextTick() // the models are on the page now
    document.getElementById(FRIGATE_PLUS_ID)?.scrollIntoView?.() // jsdom, in the tests, has no scrollIntoView
  }
})

// The two facts above the models, as the Device page's Software grid has them
const detectorValue = computed(() => state.value?.detector ?? 'Unknown')

const KINDS = {
  frigate_plus: 'a Frigate+ model',
  local: 'a local model',
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

// The sidecar's facts in one line, such as "trained 2026-10-01, yolo-generic, for edgetpu, 320×320"
function facts(model: ModelOut) {
  if (isDefaultKind(model.kind)) return model.name
  return [
    model.trained_at ? `trained ${model.trained_at.slice(0, 10)}` : null,
    model.type,
    model.detectors.length ? `for ${model.detectors.join(' or ')}` : null,
    model.width && model.height ? `${model.width}×${model.height}` : null,
  ]
    .filter(Boolean)
    .join(', ')
}

// One bordered block per model: the one Frigate runs above the fold, the rest in the "Other models" panel. A default
// with no file on the device gets a block the page makes (model null), keyed "#<kind>", which no model's name can be.
function listed(model: ModelOut): Block {
  return { key: model.name, title: titleOf(model), facts: facts(model), model, kind: model.kind, inUse: model.running }
}
function made(kind: DefaultKind, inUse: boolean): Block {
  return { key: `#${kind}`, title: DEFAULT_TITLES[kind], facts: MADE_FACTS[kind], model: null, kind, inUse }
}

const inUse = computed<Block | null>(() => {
  if (!state.value) return null
  const { running, models } = state.value
  const model = models.find((m) => m.running)
  if (model) return listed(model)
  return isDefaultKind(running.kind) ? made(running.kind, true) : null
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

// The panels that are open, by value: one list per section, because a group of panels writes back only its own
// values and would close the others' if they shared one
const modelsOpen = ref<string[]>([])
const labelsOpen = ref<string[]>([])

// The admin's actions. One runs at a time; `busy` names it ("use mine.tflite"), and `restarting` is true while the
// page waits for Frigate after a use. Each result shows where its action was: under the model, under the default's
// button (DEFAULT), or above the list (LIST) for a model that's gone. A model's name can't start with "#".
const DEFAULT = '#default'
const LIST = '#list'
const busy = ref<string | null>(null)
const restarting = ref(false)
const working = computed(() => busy.value !== null || restarting.value)
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

// What ModelBlock needs of the page's state for one block. A default's use shows its result at DEFAULT, so the
// result follows the block when it moves above the fold.
function blockProps(block: Block) {
  const at = isDefaultKind(block.kind) ? DEFAULT : block.key
  const on = (action: string) => busy.value === `${action} ${action === 'use' ? at : block.key}`
  return {
    block,
    admin: session.isAdmin,
    busy: on('use') ? 'use' : on('download') ? 'download' : on('delete') ? 'delete' : null,
    working: working.value,
    result: result.value?.at === at ? result.value : null,
    useBlocked: block.model && !isDefaultKind(block.kind) ? useBlocked(block.model) : null,
    canUse: isDefaultKind(block.kind) ? canUseDefault(block) : !block.inUse,
  } as const
}

function askToUse(block: Block) {
  if (block.model && !isDefaultKind(block.kind)) {
    confirming.value = { action: 'use', title: block.title, model: block.model }
  } else {
    const title = block.kind === 'installer_default' ? "the installer's model" : "Frigate's built-in model"
    confirming.value = { action: 'use', title, model: null }
  }
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
        <ModelBlock
          v-if="inUse"
          v-bind="blockProps(inUse)"
          class="mb-4"
          @use="askToUse(inUse)"
          @download="download(inUse.model!)"
          @remove="confirming = { action: 'delete', title: inUse.title, model: inUse.model }"
        />
        <!-- The other models in one panel, closed until tapped. Its title, a button, goes inside the h3, so the heading
             stays a heading for screen readers, as on the Device page. Eager: its content is on the page while it's
             closed, so the page's height is known when a link scrolls to the key panel. The panels take the page's
             background, so the block in use is the only tinted thing on the page. -->
        <v-expansion-panels v-model="modelsOpen" multiple flat bg-color="background">
          <v-expansion-panel value="other-models" class="border" eager>
            <h3 class="text-subtitle-1 font-weight-medium">
              <v-expansion-panel-title class="text-subtitle-1 font-weight-medium">
                Other models on this device ({{ others.length }})
              </v-expansion-panel-title>
            </h3>
            <v-expansion-panel-text>
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
              <div class="d-flex flex-column ga-3 mt-4">
                <ModelBlock
                  v-for="block in others"
                  :key="block.key"
                  v-bind="blockProps(block)"
                  @use="askToUse(block)"
                  @download="download(block.model!)"
                  @remove="confirming = { action: 'delete', title: block.title, model: block.model }"
                />
              </div>
            </v-expansion-panel-text>
          </v-expansion-panel>
        </v-expansion-panels>
      </section>

      <section class="mt-10">
        <h2 class="text-h6 mb-2">What the model recognises</h2>
        <p class="text-body-1 mb-4">Frigate tracks only the objects that are in both lists.</p>
        <v-expansion-panels v-model="labelsOpen" multiple flat bg-color="background" class="ga-3">
          <v-expansion-panel value="recognised" class="border" eager>
            <h3 class="text-subtitle-1 font-weight-medium">
              <v-expansion-panel-title class="text-subtitle-1 font-weight-medium">
                All objects the model recognises{{ state.labels.recognised ? ` (${state.labels.recognised.length})` : '' }}
              </v-expansion-panel-title>
            </h3>
            <v-expansion-panel-text>
              <LabelChips v-if="state.labels.recognised" :labels="state.labels.recognised" />
              <p v-else class="text-body-2 text-secondary">
                {{
                  state.frigate_answers
                    ? "The running model's labels aren't known."
                    : "Frigate isn't answering, and the running model has no sidecar on the device."
                }}
              </p>
            </v-expansion-panel-text>
          </v-expansion-panel>
          <v-expansion-panel value="tracked" class="border" eager>
            <h3 class="text-subtitle-1 font-weight-medium">
              <v-expansion-panel-title class="text-subtitle-1 font-weight-medium">
                Objects tracked on this device ({{ state.labels.tracked.length }})
              </v-expansion-panel-title>
            </h3>
            <v-expansion-panel-text>
              <LabelChips :labels="state.labels.tracked" />
            </v-expansion-panel-text>
          </v-expansion-panel>
        </v-expansion-panels>
      </section>
    </template>

    <!-- The last section is one panel, its title inside the h2, as the Device page's "Tokens and keys" is -->
    <section :id="FRIGATE_PLUS_ID" class="mt-10 frigate-plus">
      <v-expansion-panels v-model="keyOpen" multiple flat bg-color="background">
        <v-expansion-panel :value="FRIGATE_PLUS_ID" class="border" eager>
          <h2 class="text-h6">
            <v-expansion-panel-title class="text-h6">
              <span class="d-flex flex-wrap align-baseline key-title">
                <span>Frigate+ API key</span>
                <span v-if="keyState" class="text-body-2 text-secondary">{{ keyState }}</span>
              </span>
            </v-expansion-panel-title>
          </h2>
          <v-expansion-panel-text>
            <p class="text-body-1 mb-2">
              When the device is online and has a Frigate+ API key, pick a Frigate+ model in Frigate, under Settings,
              System, Detectors and model, and Frigate downloads it.
            </p>
            <p class="text-body-1" :class="{ 'mb-6': session.isAdmin }">
              When it's offline, an administrator can upload the model's two files on this page, as a package from
              whoever trained the model or copied from another device's Frigate.
            </p>
            <template v-if="session.isAdmin">
              <v-alert v-if="secretsError" type="error">
                {{ secretsError }}
                <template #append>
                  <v-btn variant="text" @click="loadSecrets">Try again</v-btn>
                </template>
              </v-alert>
              <v-progress-linear v-else-if="!secrets" indeterminate color="primary" />
              <EnteredSecret v-if="key" :secret="key" hide-title @changed="loadSecrets" />
            </template>
          </v-expansion-panel-text>
        </v-expansion-panel>
      </v-expansion-panels>
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

/* The key's state beside its name, or under it when the title wraps (Vuetify 3.13 has no column-gap class) */
.key-title {
  column-gap: 12px;
}
</style>
