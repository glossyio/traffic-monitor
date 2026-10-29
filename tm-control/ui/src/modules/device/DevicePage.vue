<!--
  The Device page (GET /system/info): the device card, the software versions, and for admins the diagnostics file
  (GET /system/diagnostics) and the power buttons (POST /system/reboot and /system/power-off, each after a
  confirmation). Viewers see the card and the versions only.
-->
<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import { duration } from '../../components/relative-time'
import StatusCard from '../../components/StatusCard.vue'
import { useSession } from '../../stores/session'

type SystemInfo = components['schemas']['SystemInfo']
type Throttled = components['schemas']['Throttled']

const GIB = 2 ** 30

const session = useSession()
const info = ref<SystemInfo | null>(null)
const loadError = ref('')

async function load() {
  loadError.value = ''
  try {
    const { data } = await api.GET('/api/v1/system/info')
    info.value = data as SystemInfo
  } catch (error) {
    loadError.value = messageOf(error)
  }
}

onMounted(load)

// Bytes as GB, counted in powers of 1024 as the status checks count them: "7.5 GB" under 10, "58 GB" from 10 up
function gb(bytes: number) {
  const value = bytes / GIB
  return `${value < 10 ? value.toFixed(1) : Math.round(value)} GB`
}

// The firmware's power flags in words
const FLAGS: Record<Throttled['now'][number], string> = {
  'under-voltage': 'under-voltage',
  'frequency-capped': 'speed capped',
  throttled: 'throttled',
  'soft-temperature-limit': 'temperature limit',
}

function power(throttled: Throttled | null) {
  if (!throttled) return 'Unknown'
  const words = (flags: Throttled['now']) => flags.map((flag) => FLAGS[flag]).join(', ')
  if (throttled.now.length) return `Now: ${words(throttled.now)}`
  if (throttled.since_boot.length) return `OK now; ${words(throttled.since_boot)} since it started`
  return 'OK'
}

// The commit tmsetup installed from. A release tag's checkout has no branch (git says HEAD).
function commit(tm: SystemInfo['tm']) {
  if (!tm.commit || tm.commit === 'unknown') return 'Unknown'
  const branch = tm.branch && !['HEAD', 'unknown'].includes(tm.branch) ? ` on ${tm.branch}` : ''
  return `${tm.commit.slice(0, 7)}${branch}`
}

const subtitle = computed(() => {
  if (!info.value) return []
  const { model, memory, tm } = info.value
  const board = [model, memory ? `${Math.round(memory.total / GIB)} GB memory` : null].filter(Boolean).join(', ')
  return [board, `Traffic Monitor ${tm.version}`].filter(Boolean)
})

const facts = computed(() => {
  if (!info.value) return []
  const { serial, uptime_seconds, disks, soc_temperature_c, throttled } = info.value
  // The API reads / and the code directory. On the same card they report the same size, so show each size once.
  const storage = []
  const sizes = new Set<number>()
  for (const disk of disks) {
    if (sizes.has(disk.total)) continue
    sizes.add(disk.total)
    storage.push({
      label: storage.length === 0 ? 'Storage' : `Storage for ${disk.path}`,
      value: `${gb(disk.free)} free of ${gb(disk.total)}`,
      progress: disk.total > 0 ? Math.round((disk.used / disk.total) * 100) : 0,
    })
  }
  return [
    { label: 'Serial number', value: serial },
    { label: 'Running for', value: uptime_seconds === null ? 'Unknown' : duration(uptime_seconds) },
    ...storage,
    { label: 'Temperature', value: soc_temperature_c === null ? 'Unknown' : `${Math.round(soc_temperature_c)} °C` },
    { label: 'Power', value: power(throttled) },
  ]
})

const NAMES: Record<string, string> = {
  frigate: 'Frigate',
  node_red: 'Node-RED',
  go2rtc: 'go2rtc',
  nginx: 'nginx',
  hailo: 'Hailo',
}

const software = computed(() => {
  if (!info.value) return []
  const { components: versions, tm, os, kernel } = info.value
  return [
    ...Object.entries(versions).map(([key, version]) => ({ label: NAMES[key] ?? key, value: version.replace(/^v/, '') })),
    { label: 'Commit', value: commit(tm) },
    { label: 'Operating system', value: os ?? 'Unknown' },
    { label: 'Kernel', value: kernel ?? 'Unknown' },
  ]
})

// Diagnostics: the text file a support request needs. The API removes passwords and keys before sending it.
const fetching = ref<'download' | 'copy' | null>(null)
const diagnosticsResult = ref<{ text: string; error: boolean } | null>(null)

async function diagnostics(): Promise<{ text: string; filename: string }> {
  const { data, response } = await api.GET('/api/v1/system/diagnostics', { parseAs: 'text' })
  const match = /filename="([^"]+)"/.exec(response.headers.get('Content-Disposition') ?? '')
  return { text: data ?? '', filename: match?.[1] ?? 'tm-diagnostics.txt' }
}

async function download() {
  fetching.value = 'download'
  diagnosticsResult.value = null
  copyByHand.value = null
  try {
    const { text, filename } = await diagnostics()
    // Save the text as a file: a link to it in memory, with the server's file name, clicked once. Some browsers
    // only follow a link that's in the page, and still read the file after click() returns, so it's freed later.
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    document.body.append(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (error) {
    diagnosticsResult.value = { text: messageOf(error), error: true }
  } finally {
    fetching.value = null
  }
}

// Select all of a textarea's text. iOS Safari ignores select() on a read-only textarea, so set the range as well.
function selectAll(area: HTMLTextAreaElement) {
  area.focus()
  area.select()
  area.setSelectionRange(0, area.value.length)
}

// navigator.clipboard only exists on HTTPS, and the device is usually reached over plain HTTP. The older way works
// on both: put the text in a textarea, select it, and ask the browser to copy the selection. The browser may still
// refuse, because the tap that asked for it was a while ago once the diagnostics have arrived (iOS Safari is strict).
async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // fall through to the older way
    }
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed' // off the page, so the page doesn't scroll to it
  area.style.opacity = '0'
  document.body.append(area)
  selectAll(area)
  try {
    return document.execCommand('copy')
  } catch {
    return false
  } finally {
    area.remove()
  }
}

// When the browser won't copy, the text goes in a box on the page, selected, for the person to copy by hand
const copyByHand = ref<string | null>(null)
const copyBox = ref<{ $el: HTMLElement } | null>(null)

async function copy() {
  fetching.value = 'copy'
  diagnosticsResult.value = null
  copyByHand.value = null
  try {
    const { text } = await diagnostics()
    if (await copyText(text)) {
      diagnosticsResult.value = { text: 'Copied. Paste it into your support request.', error: false }
    } else {
      diagnosticsResult.value = {
        text: "This browser didn't let the page copy. Copy the text from the box below.",
        error: false,
      }
      copyByHand.value = text
      await nextTick() // the box is on the page now
      const area = copyBox.value?.$el.querySelector('textarea')
      if (area) {
        selectAll(area)
        area.scrollTop = 0 // selecting scrolls to the end; show the start of the file
      }
    }
  } catch (error) {
    diagnosticsResult.value = { text: messageOf(error), error: true }
  } finally {
    fetching.value = null
  }
}

// Reboot and shut down, each after a confirmation. The API refuses (409) while something such as an update holds
// shutdown off; then the page says so and stays as it was.
type PowerAction = 'reboot' | 'power-off'
const POWER = {
  reboot: {
    title: 'Reboot the device?',
    text: 'The device will be unreachable for about two minutes.',
    confirm: 'Reboot',
    done: 'Rebooting. This page will stop answering for about two minutes.',
  },
  'power-off': {
    title: 'Shut down the device?',
    text: 'The device will turn off. To start it again, unplug it and plug it back in.',
    confirm: 'Shut down',
    done: 'Shutting down. To start the device again, unplug it and plug it back in.',
  },
}
const confirming = ref<PowerAction | null>(null)
const confirmOpen = computed({
  get: () => confirming.value !== null,
  set: (open: boolean) => {
    if (!open) confirming.value = null
  },
})
const powering = ref<PowerAction | null>(null)
const powerDone = ref('')
const powerError = ref('')

async function powerAction() {
  const action = confirming.value
  if (!action) return
  powering.value = action
  powerError.value = ''
  try {
    if (action === 'reboot') await api.POST('/api/v1/system/reboot')
    else await api.POST('/api/v1/system/power-off')
    powerDone.value = POWER[action].done
  } catch (error) {
    powerError.value = messageOf(error)
  } finally {
    powering.value = null
  }
}
</script>

<template>
  <div>
    <h1 class="text-h5 text-primary mb-6">Device</h1>

    <v-alert v-if="loadError" type="error" class="mb-6">
      {{ loadError }}
      <template #append>
        <v-btn variant="text" @click="load">Try again</v-btn>
      </template>
    </v-alert>
    <v-progress-linear v-else-if="!info" indeterminate color="primary" />

    <template v-if="info">
      <StatusCard :title="info.hostname" :subtitle="subtitle" :items="facts" />

      <section class="mt-10">
        <h2 class="text-h6 mb-4">Software</h2>
        <v-row dense>
          <v-col v-for="item in software" :key="item.label" cols="6" sm="4">
            <div class="text-body-2 text-secondary">{{ item.label }}</div>
            <div class="text-body-1 text-break">{{ item.value }}</div>
          </v-col>
        </v-row>
      </section>

      <template v-if="session.isAdmin">
        <section class="mt-10">
          <h2 class="text-h6 mb-2">Diagnostics</h2>
          <p class="text-body-1 mb-4">
            A text file with the device's state and recent logs, for a support request. Passwords and keys are
            removed.
          </p>
          <div class="d-flex flex-wrap ga-3">
            <v-btn
              color="primary"
              size="large"
              :loading="fetching === 'download'"
              :disabled="fetching !== null"
              @click="download"
            >
              Download diagnostics
            </v-btn>
            <v-btn
              variant="outlined"
              color="primary"
              size="large"
              :loading="fetching === 'copy'"
              :disabled="fetching !== null"
              @click="copy"
            >
              Copy
            </v-btn>
          </div>
          <v-alert v-if="diagnosticsResult?.error" type="error" class="mt-4">{{ diagnosticsResult.text }}</v-alert>
          <p v-else-if="diagnosticsResult" class="text-body-1 mt-4">{{ diagnosticsResult.text }}</p>
          <!-- Fixed height, so the long text scrolls inside the box rather than stretching the page -->
          <v-textarea
            v-if="copyByHand !== null"
            ref="copyBox"
            :model-value="copyByHand"
            label="Diagnostics"
            variant="outlined"
            readonly
            rows="10"
            no-resize
            hide-details
            class="mt-4"
          />
        </section>

        <section class="mt-10">
          <h2 class="text-h6 mb-4">Power</h2>
          <p v-if="powerDone" class="text-body-1">{{ powerDone }}</p>
          <div v-else class="d-flex flex-wrap ga-3">
            <v-btn
              variant="outlined"
              color="primary"
              size="large"
              :loading="powering === 'reboot'"
              :disabled="powering !== null"
              @click="confirming = 'reboot'"
            >
              Reboot the device
            </v-btn>
            <v-btn
              variant="outlined"
              color="primary"
              size="large"
              :loading="powering === 'power-off'"
              :disabled="powering !== null"
              @click="confirming = 'power-off'"
            >
              Shut down the device
            </v-btn>
          </div>
          <v-alert v-if="powerError" type="error" class="mt-4">{{ powerError }}</v-alert>
        </section>
      </template>
    </template>

    <ConfirmDialog
      v-model="confirmOpen"
      :title="confirming ? POWER[confirming].title : ''"
      :text="confirming ? POWER[confirming].text : ''"
      :confirm-text="confirming ? POWER[confirming].confirm : ''"
      @confirm="powerAction"
    />
  </div>
</template>
