<!--
  The Software update page, for admins (GET /update). Top to bottom: what is installed; the last run, while it goes and
  after it ends; then, when no run is going, the channel, Check for updates (POST /update/check, the one request that
  makes the device ask GitHub), what the check found, the checks before a start, and Update to <version>
  (POST /update/start). The log (GET /update/log) is a folded panel at the end, loaded when it is opened.
  The device decides everything; the page only words its answers (words.ts) and follows a run (useUpdate in update.ts).
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, messageOf } from '../../api/client'
import CheckList from '../../components/CheckList.vue'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import CopyButton from '../../components/CopyButton.vue'
import { agoAt } from '../../components/relative-time'
import RunProgress from './RunProgress.vue'
import { following, useUpdate, type Offer, type Run, type UpdateState } from './update'
import { BEFORE_SWITCH, INSTALLER_DOCS, reasonLink, reasonWords, type ReasonLink } from './words'

type Channel = 'stable' | 'development'
type UpdateLog = { run_id: string | null; job: string[]; log: string[] }

const CONFIRM_TEXT =
  'The device keeps counting while it downloads and builds the new version, which can take half an hour. It then ' +
  'stops for a few minutes, and it may restart.'
const CHANNEL_NAMES: Record<string, string> = { stable: 'Stable', development: 'Development' }

const { state, lost, loadError, refresh, show } = useUpdate()

// Installed: "Traffic Monitor 0.8.0 · Stable · commit 2da617a", with ", modified" for a changed copy
const installedLine = computed(() => {
  const installed = state.value?.installed
  if (!installed) return ''
  const channel = CHANNEL_NAMES[installed.channel] ?? installed.channel
  const modified = installed.modified ? ', modified' : ''
  return `Traffic Monitor ${installed.version} · ${channel} · commit ${installed.commit.slice(0, 7)}${modified}`
})

// The channel the next check asks about. It starts as the installed one, and again whenever the device names another.
const channel = ref<Channel>('stable')
watch(
  () => state.value?.installed.channel,
  (installed) => {
    if (installed === 'stable' || installed === 'development') channel.value = installed
  },
)

// What the last check found, when it was for the channel chosen now
const offer = computed<Offer | null>(() => {
  const found = state.value?.offer ?? null
  return found && found.channel === channel.value ? found : null
})
const ahead = computed(() => offer.value?.relation === 'ahead')

// "0.8.1", or "commit 6666666" on Development
function targetName(version: string | null | undefined, commit: string | null | undefined): string {
  if (version) return version
  return commit ? `commit ${commit.slice(0, 7)}` : ''
}

// A Development offer: "12 changes since this version are available (commit 6666666)."
function changesLine(found: Offer): string {
  const commit = `(commit ${found.commit.slice(0, 7)})`
  if (found.ahead_by === 1) return `1 change since this version is available ${commit}.`
  if (found.ahead_by === null) return `Changes since this version are available ${commit}.`
  return `${found.ahead_by} changes since this version are available ${commit}.`
}

function releasedOn(iso: string | null): string {
  const moment = iso === null ? NaN : Date.parse(iso)
  if (Number.isNaN(moment)) return ''
  return new Date(moment).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

// "Last checked 5 minutes ago" moves on by itself
const now = ref(Date.now())
let tick: ReturnType<typeof setInterval> | undefined

// Check for updates, and the start. Each one's failure shows under the button that was pressed.
const checking = ref(false)
const checkError = ref('')
const starting = ref(false)
const startError = ref('')
const startedFrom = ref<'offer' | 'retry'>('offer') // which button the start came from

async function check() {
  checking.value = true
  checkError.value = ''
  startError.value = ''
  try {
    const { data } = await api.POST('/api/v1/update/check', { body: { channel: channel.value } })
    show(data as UpdateState)
    now.value = Date.now()
  } catch (error) {
    checkError.value = messageOf(error)
  } finally {
    checking.value = false
  }
}

// Starting: the offer's target from Update to ..., or the last run's (`retry`) from Try again and Finish the update.
// Update to ... and Try again ask first. Finish the update doesn't: it carries on a switch that was already confirmed.
const confirming = ref<{ channel: Channel; commit: string; from: 'offer' | 'retry' } | null>(null)
const confirmOpen = computed({
  get: () => confirming.value !== null,
  set: (open: boolean) => {
    if (!open) confirming.value = null
  },
})
const confirmTitle = computed(() => {
  if (confirming.value?.from === 'retry') return 'Try the update again'
  return `Update to ${targetName(offer.value?.version, offer.value?.commit)}`
})

function askToStart() {
  const found = offer.value
  if (found) confirming.value = { channel: found.channel, commit: found.commit, from: 'offer' }
}

function askToRetry() {
  const retry = state.value?.retry
  if (retry) confirming.value = { channel: retry.channel as Channel, commit: retry.commit, from: 'retry' }
}

function finish() {
  const retry = state.value?.retry
  if (retry) void start(retry.channel as Channel, retry.commit, 'retry')
}

function confirmed() {
  const target = confirming.value
  if (target) void start(target.channel, target.commit, target.from)
}

async function start(target: Channel, commit: string, from: 'offer' | 'retry') {
  starting.value = true
  startError.value = ''
  checkError.value = ''
  startedFrom.value = from
  try {
    const { data } = await api.POST('/api/v1/update/start', { body: { channel: target, commit } })
    show(data as UpdateState)
  } catch (error) {
    startError.value = messageOf(error)
  } finally {
    starting.value = false
  }
}

// The run, and whether this page saw it going: after an update that ended ok, a page open before it is the old
// version's, and offers Reload.
const run = computed<Run | null>(() => state.value?.run ?? null)
const going = computed(() => following(state.value))
const sawRun = ref(false)
watch(going, (isGoing) => {
  if (isGoing) sawRun.value = true
})

const runTitle = computed(() => {
  if (!run.value) return 'Starting the update'
  const name = targetName(run.value.to_version, run.value.to_commit)
  return name ? `Updating to ${name}` : 'An update is running.'
})

// How the last run ended: its words (and a link), the button that carries on from it, and, after an update that ended
// ok while this page was open, Reload. A start the device refused comes first, being newer than the run.
interface Ending {
  title: string
  type: 'success' | 'error' | 'warning'
  lines: string[]
  link: ReasonLink | null
  button: 'Try again' | 'Finish the update' | null
  reload: boolean
}

const LAST = 'Last update'

const ending = computed<Ending | null>(() => {
  const started = state.value?.started
  if (started?.status === 'failed') {
    const words = reasonWords(started.reason === 'busy' ? 'busy' : null)
    return { title: "The update didn't start", type: 'error', lines: [words], link: null, button: null, reload: false }
  }
  const last = run.value
  if (!last || last.status === 'running') return null
  const canRetry = state.value?.retry != null
  if (last.status === 'ok') {
    const words = `Updated to ${targetName(last.to_version, last.to_commit)}.`
    return { title: LAST, type: 'success', lines: [words], link: null, button: null, reload: sawRun.value }
  }
  if (last.status === 'failed') {
    const lines = [reasonWords(last.reason ?? null)]
    if (last.detail) lines.push(`Detail: ${last.detail}`)
    const button = canRetry ? 'Try again' : null
    return { title: LAST, type: 'error', lines, link: reasonLink(last.reason ?? null), button, reload: false }
  }
  if (last.status === 'interrupted') {
    const lines = ['The update stopped before it finished (a restart or a power cut).']
    if (!last.stage || BEFORE_SWITCH.has(last.stage)) lines.push('Nothing was changed.')
    return { title: LAST, type: 'warning', lines, link: null, button: canRetry ? 'Try again' : null, reload: false }
  }
  // cut_off: the switch had begun, and starting the same target again finishes it
  const lines = ['The update was cut off while it was switching.']
  return { title: LAST, type: 'warning', lines, link: null, button: canRetry ? 'Finish the update' : null, reload: false }
})

// Check for updates is the page's main (filled) button unless another one is: Update to ..., or the last run's button
const checkIsMain = computed(() => !ahead.value && !ending.value?.button && !ending.value?.reload)

function pressEnding(button: string) {
  if (button === 'Finish the update') finish()
  else askToRetry()
}

function reload() {
  window.location.reload()
}

// The log, loaded each time its panel is opened
const logOpen = ref<string | null>(null)
const log = ref<UpdateLog | null>(null)
const logLoading = ref(false)
const logError = ref('')
const logText = computed(() => {
  const found = log.value
  if (!found) return ''
  return [...found.log, ...(found.log.length && found.job.length ? [''] : []), ...found.job].join('\n')
})

async function loadLog() {
  logLoading.value = true
  logError.value = ''
  try {
    const { data } = await api.GET('/api/v1/update/log')
    log.value = data as UpdateLog
  } catch (error) {
    logError.value = messageOf(error)
  } finally {
    logLoading.value = false
  }
}

watch(logOpen, (open) => {
  if (open) void loadLog()
})

onMounted(() => {
  void refresh()
  tick = setInterval(() => (now.value = Date.now()), 15_000)
})
onBeforeUnmount(() => clearInterval(tick))

const lastChecked = computed(() => (offer.value ? `Last checked ${agoAt(offer.value.checked_at, now.value)}` : ''))
const beforeStart = computed(() => ({ id: 'update-checks', title: 'Before you start', checks: state.value?.checks ?? [] }))
</script>

<template>
  <div>
    <h1 class="text-h5 text-primary mb-6">Software update</h1>

    <v-alert v-if="loadError" type="error" class="mb-6">
      {{ loadError }}
      <template #append>
        <v-btn variant="text" @click="refresh">Try again</v-btn>
      </template>
    </v-alert>
    <v-progress-linear v-else-if="!state" indeterminate color="primary" />

    <template v-if="state">
      <p class="text-body-1">{{ installedLine }}</p>

      <!-- The run: its stages while it goes, and how it ended, in the same place -->
      <section v-if="going" class="mt-8">
        <h2 class="text-h6 mb-2">{{ runTitle }}</h2>
        <p v-if="run && !run.readable" class="text-body-1 mb-2">
          This version of the page can't read its stages. The log below shows how it goes.
        </p>
        <RunProgress v-if="run" :run="run" :lost="lost" />
        <template v-else>
          <v-alert v-if="lost" type="info" variant="tonal" class="mb-4">
            The device isn't answering. That is expected for a few minutes while it switches or restarts. This page
            keeps trying.
          </v-alert>
          <p class="text-body-1">You can close this page. The update carries on.</p>
        </template>
      </section>

      <section v-else-if="ending" class="mt-8">
        <h2 class="text-h6 mb-2">{{ ending.title }}</h2>
        <v-alert :type="ending.type" variant="tonal">
          <p v-for="(line, index) in ending.lines" :key="index" :class="{ 'mt-2': index > 0 }">{{ line }}</p>
          <p v-if="ending.link" class="mt-2">
            <a v-if="ending.link.external" :href="ending.link.href" class="text-primary">{{ ending.link.text }}</a>
            <router-link v-else :to="ending.link.href" class="text-primary">{{ ending.link.text }}</router-link>
          </p>
        </v-alert>
        <RunProgress v-if="run && run.status !== 'ok' && !state.started" :run="run" :lost="false" class="mt-4" />
        <template v-if="ending.reload">
          <p class="text-body-1 mt-4">This page is from the version before.</p>
          <v-btn color="primary" variant="flat" size="large" class="mt-4" @click="reload">Reload</v-btn>
        </template>
        <v-btn
          v-if="ending.button"
          color="primary"
          variant="flat"
          size="large"
          class="mt-4"
          :loading="starting"
          @click="pressEnding(ending.button)"
        >
          {{ ending.button }}
        </v-btn>
        <v-alert v-if="startError && startedFrom === 'retry'" type="error" class="mt-4">{{ startError }}</v-alert>
      </section>

      <!-- Looking for an update: not while one runs, which would refuse a start anyway -->
      <template v-if="!going">
        <section class="mt-8">
          <h2 class="text-h6 mb-2">Channel</h2>
          <v-radio-group v-model="channel" aria-label="Channel" color="primary" hide-details>
            <v-radio value="stable" label="Stable releases" />
            <v-radio value="development" label="Development (newest, can break)" />
          </v-radio-group>
          <!-- Under the Development choice, lined up with its label (the radio button is 40 px wide) -->
          <p class="text-body-2 text-secondary ps-10">
            A device on Development goes back to Stable only when the next release comes out.
          </p>
        </section>

        <section class="mt-6">
          <div class="d-flex flex-wrap align-center ga-4">
            <!-- The page's main button until there is something else to press -->
            <v-btn
              color="primary"
              :variant="checkIsMain ? 'flat' : 'outlined'"
              size="large"
              :loading="checking"
              @click="check"
            >
              Check for updates
            </v-btn>
            <span v-if="lastChecked" class="text-body-2 text-secondary">{{ lastChecked }}</span>
          </div>
          <p class="text-body-2 text-secondary mt-2">Checking asks GitHub. Nothing is sent until you press it.</p>
          <v-alert v-if="checkError" type="error" class="mt-4">{{ checkError }}</v-alert>
        </section>

        <section v-if="offer" class="mt-6">
          <template v-if="offer.relation === 'ahead'">
            <p v-if="offer.version" class="text-body-1">Version {{ offer.version }} is available.</p>
            <p v-else class="text-body-1">{{ changesLine(offer) }}</p>
            <p v-if="releasedOn(offer.released_at)" class="text-body-2 text-secondary">
              Released {{ releasedOn(offer.released_at) }}
            </p>
          </template>
          <p v-else-if="offer.relation === 'identical'" class="text-body-1">This device is up to date.</p>
          <p v-else-if="offer.relation === 'behind'" class="text-body-1">This device is newer than the latest release.</p>
          <p v-else class="text-body-1">
            This device can't be updated from here. Update it with the installer.
            <a :href="INSTALLER_DOCS" class="text-primary">How to update with the installer</a>
          </p>
        </section>

        <template v-if="ahead && offer">
          <section class="mt-8">
            <CheckList v-if="beforeStart.checks.length" :group="beforeStart" :admin="false" :busy="null" />
            <h2 v-else class="text-h6 mb-1">Before you start</h2>
            <p class="text-body-1 mt-2">
              The update saves the settings as a restore point. It doesn't save the counted data:
              <a href="/dashboard/" class="text-primary">download the database</a> first.
            </p>
          </section>

          <v-btn
            color="primary"
            variant="flat"
            size="large"
            class="mt-6"
            :disabled="!state.can_start"
            :loading="starting && startedFrom === 'offer'"
            @click="askToStart"
          >
            Update to {{ targetName(offer.version, offer.commit) }}
          </v-btn>
          <v-alert v-if="startError && startedFrom === 'offer'" type="error" class="mt-4">{{ startError }}</v-alert>
        </template>
      </template>

      <!-- One expansion panel, its title inside the h2, as on the Device page -->
      <section class="mt-10">
        <v-expansion-panels v-model="logOpen" flat>
          <v-expansion-panel value="log" class="border">
            <h2 class="text-h6">
              <v-expansion-panel-title class="text-h6">Log</v-expansion-panel-title>
            </h2>
            <v-expansion-panel-text>
              <v-alert v-if="logError" type="error">{{ logError }}</v-alert>
              <v-progress-linear v-else-if="logLoading && !log" indeterminate color="primary" />
              <template v-if="log">
                <p v-if="!logText" class="text-body-1">The log is empty.</p>
                <template v-else>
                  <div class="d-flex align-center justify-end ga-2 mb-2">
                    <v-btn variant="text" :loading="logLoading" @click="loadLog">Refresh</v-btn>
                    <CopyButton :text="logText" label="the log" />
                  </div>
                  <v-sheet
                    border
                    rounded="lg"
                    max-height="360"
                    class="overflow-y-auto pa-3 text-body-2 text-mono text-pre-wrap text-break"
                  >{{ logText }}</v-sheet>
                </template>
              </template>
            </v-expansion-panel-text>
          </v-expansion-panel>
        </v-expansion-panels>
      </section>
    </template>

    <ConfirmDialog
      v-model="confirmOpen"
      :title="confirmTitle"
      :text="CONFIRM_TEXT"
      confirm-text="Start the update"
      confirm-color="primary"
      @confirm="confirmed"
    />
  </div>
</template>
