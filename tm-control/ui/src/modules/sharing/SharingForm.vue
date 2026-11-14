<!--
  The sharing form, for admins: which server the device uploads to, its access token, the three choices about what
  leaves the device (each its own box, none ticked until the person ticks it), the notice, and Save (PUT /sharing).
  `state` is what GET /sharing says; the form copies it into its own fields and starts again from it whenever the
  saved choices change (not when only the token's state or the server's answer does, so typing isn't lost). Emits
  `saved` with the state the API answers a save with, and `reload` when the page should read /sharing again (the token
  changed, or config.yml changed under a save). With `firstRun`, the button reads "Save and finish": the first-run
  steps reuse this form.
-->
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { ApiError, api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import EnteredSecret from '../../components/EnteredSecret.vue'
import EulaText from '../../components/EulaText.vue'
import ConsentBox from './ConsentBox.vue'
import { EXACT_LOCATION_EXAMPLE, PUBLIC_MAP_EXAMPLE, SHARE_DATA_EXAMPLE } from './examples'

type SharingState = components['schemas']['SharingState']
type ConsentOut = components['schemas']['ConsentOut']
type Notice = components['schemas']['NoticeOut']
type Target = 'maintainer' | 'own'

const props = defineProps<{ state: SharingState; firstRun?: boolean }>()
const emit = defineEmits<{ saved: [state: SharingState]; reload: [] }>()

const NOT_ON: ConsentOut = { granted: false, at: null, notice_version: null }
const normalize = (host: string | null) => (host ?? '').trim().toLowerCase()

// The form's own fields. They start as the saved state and change as the person edits.
const target = ref<Target>('maintainer')
const host = ref('')
const protocol = ref<'https' | 'http'>('https')
const port = ref('')
const shareData = ref(false)
const exactLocation = ref(false)
const publicMap = ref(false)
const noticeRead = ref(false)

function load(state: SharingState) {
  target.value = state.target ?? 'maintainer'
  host.value = state.target === 'own' ? (state.host ?? '') : ''
  protocol.value = state.protocol
  port.value = state.port === null ? '' : String(state.port)
  shareData.value = state.enabled
  exactLocation.value = state.enabled && state.exact_location.granted
  publicMap.value = state.enabled && state.public_map.granted
  noticeRead.value = false
}
load(props.state)

// Starts the fields again when the saved choices change, and only then
const saved = computed(() => {
  const { enabled, target, host, protocol, port, share_data, exact_location, public_map, notice_version } = props.state
  return JSON.stringify([enabled, target, host, protocol, port, share_data, exact_location, public_map, notice_version])
})
watch(saved, () => load(props.state))

// Changing the server (the maintainer's, or an own server's host) ends the choices made for the old one
const serverChanged = computed(() => {
  if (props.state.target === null) return false
  if (target.value !== props.state.target) return true
  return target.value === 'own' && normalize(host.value) !== normalize(props.state.host)
})
const recorded = (consent: ConsentOut) => (serverChanged.value ? NOT_ON : consent)
watch(serverChanged, (changed) => {
  exactLocation.value = !changed && props.state.enabled && props.state.exact_location.granted
  publicMap.value = !changed && props.state.enabled && props.state.public_map.granted
})

// Why a box can't be ticked now, or ''. A box that is already ticked stays enabled, so it can always be withdrawn.
const shareDataReason = computed(() => (props.state.token?.set ? '' : 'Set the access token first.'))
const exactReason = computed(() => {
  if (!shareData.value) return 'Turn on Share data first.'
  if (target.value === 'own' && protocol.value === 'http') return 'The exact location is only sent over https.'
  return ''
})
const mapReason = computed(() => {
  if (!props.state.public_map_live) return 'Not live yet.'
  return shareData.value ? '' : 'Turn on Share data first.'
})
// What the other boxes need ends with them: no Share data, no exact location and no map
watch(exactReason, (reason) => {
  if (reason) exactLocation.value = false
})
watch(shareData, (on) => {
  if (!on) publicMap.value = false
})

// The notice (the maintainer's server only), asked for when the save adds something to what is shared: Share data
// turned on, the server just changed to the maintainer's, or a choice newly ticked under a notice that has changed.
// A save that only keeps or withdraws choices never needs it.
const addsChoice = computed(
  () =>
    (exactLocation.value && !props.state.exact_location.granted) || (publicMap.value && !props.state.public_map.granted),
)
const noticeNeeded = computed(
  () =>
    target.value === 'maintainer' &&
    shareData.value &&
    (!props.state.enabled ||
      !props.state.share_data.granted ||
      props.state.target !== 'maintainer' ||
      (!props.state.notice_current && addsChoice.value)),
)
const noticeOpen = ref(false)
const notice = ref<Notice | null>(null)
const noticeError = ref('')

async function toggleNotice() {
  noticeOpen.value = !noticeOpen.value
  if (!noticeOpen.value || notice.value) return
  noticeError.value = ''
  try {
    const { data } = await api.GET('/api/v1/sharing/notice')
    notice.value = data as Notice
  } catch (failure) {
    noticeError.value = messageOf(failure)
  }
}

const tokenLine = computed(() => {
  const token = props.state.token
  if (!token?.set) return 'Not set.'
  return token.ends_with ? `Set, ending in ${token.ends_with}.` : 'Set.'
})

// A port is a whole number from 1 to 65535, or empty
const portNumber = computed(() => (port.value.trim() === '' ? null : Number(port.value.trim())))
const portError = computed(() => {
  const number = portNumber.value
  if (number === null || (Number.isInteger(number) && number >= 1 && number <= 65535)) return ''
  return 'Enter a port from 1 to 65535, or leave this empty.'
})

const saving = ref(false)
const error = ref('')
const hostError = ref('')
const done = ref(false)
const confirmOpen = ref(false)

watch(host, () => (hostError.value = ''))
// "Saved." describes the form as it was saved
watch([target, host, protocol, port, shareData, exactLocation, publicMap], () => (done.value = false))

function ask() {
  // The exact location and the public map were given for the server in use; a new server starts without them
  const given = props.state.exact_location.granted || props.state.public_map.granted
  if (serverChanged.value && given) confirmOpen.value = true
  else void save()
}

async function save() {
  if (portError.value) return
  saving.value = true
  error.value = ''
  hostError.value = ''
  done.value = false
  const own = target.value === 'own'
  const body = {
    target: target.value,
    host: own ? host.value.trim() : null,
    protocol: own ? protocol.value : ('https' as const),
    port: own ? portNumber.value : null,
    enabled: shareData.value,
    exact_location: shareData.value && exactLocation.value,
    public_map: target.value === 'maintainer' && shareData.value && publicMap.value ? ('rounded_point' as const) : ('none' as const),
    notice_version: noticeNeeded.value && noticeRead.value ? props.state.notice_version : null,
  }
  try {
    const { data } = await api.PUT('/api/v1/sharing', { body })
    emit('saved', data as SharingState)
    await nextTick() // the fields start again from the saved state first, which would clear the note
    done.value = true
  } catch (failure) {
    const field = failure instanceof ApiError ? (failure.detail as { field?: string } | null)?.field : undefined
    if (field === 'host') hostError.value = messageOf(failure)
    else error.value = messageOf(failure)
    // The file was edited by hand while this page was open: show what it says now
    if (failure instanceof ApiError && failure.code === 'config_changed') emit('reload')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div>
    <section>
      <h2 class="text-h6 mb-2">Server</h2>
      <v-radio-group v-model="target" aria-label="Server" hide-details>
        <v-radio value="maintainer" :label="`Traffic Monitor's server (${state.maintainer_host})`" />
        <v-radio value="own" label="Your own ThingsBoard server" />
      </v-radio-group>
      <template v-if="target === 'own'">
        <v-text-field
          v-model="host"
          label="Host"
          hint="The server's name or address, with no https:// and no path."
          persistent-hint
          :error-messages="hostError"
          autocomplete="off"
          autocapitalize="none"
          spellcheck="false"
          class="mt-4"
        />
        <v-select v-model="protocol" :items="['https', 'http']" label="Protocol" variant="outlined" class="mt-4" hide-details />
        <v-text-field
          v-model="port"
          label="Port (optional)"
          inputmode="numeric"
          :error-messages="portError"
          autocomplete="off"
          class="mt-4"
        />
        <p class="text-body-1 mt-2">
          Your own server is yours to run. The notice below doesn't apply to it, and once data leaves this device,
          making sure that server honours the choices you make here is your responsibility.
        </p>
      </template>
    </section>

    <section id="token" class="mt-10 token">
      <h2 class="text-h6 mb-1">Access token</h2>
      <p class="text-body-2 text-secondary mb-3">{{ tokenLine }}</p>
      <p class="text-body-1 mb-4">
        The server gives each device a token. Saving it restarts Node-RED, which takes about thirty seconds.
      </p>
      <!-- The token has a Save of its own, apart from the form's: its name and the border keep the two apart -->
      <v-sheet v-if="state.token" border rounded="lg" color="surface" class="pa-4">
        <EnteredSecret :secret="state.token" hide-title save-text="Save token" @changed="emit('reload')" />
      </v-sheet>
    </section>

    <section class="mt-10">
      <h2 class="text-h6 mb-2">What this device shares</h2>
      <ConsentBox
        v-model="shareData"
        title="Share data"
        text="Counts, speeds, radar and air-quality readings, and system health, with the location as the database stores it (about 1 km unless you changed it on the Location page). Turning this off stops all uploads."
        :example="SHARE_DATA_EXAMPLE"
        :disabled="!!shareDataReason && !shareData"
        :disabled-reason="shareDataReason"
        :recorded="state.share_data"
      />
      <ConsentBox
        v-model="exactLocation"
        class="mt-6"
        title="Share the exact location"
        text="This device's exact coordinates. Turning this off stops them being sent."
        :example="EXACT_LOCATION_EXAMPLE"
        :disabled="!!exactReason && !exactLocation"
        :disabled-reason="exactReason"
        :recorded="recorded(state.exact_location)"
      />
      <p v-if="!state.has_location" class="text-body-1 ms-10">
        Nothing is sent until the place in use has a location.
      </p>
      <ConsentBox
        v-if="target === 'maintainer'"
        v-model="publicMap"
        class="mt-6"
        title="Show this device on the public map"
        text="A point rounded to about 100 m, and nothing else about where the device is."
        :example="PUBLIC_MAP_EXAMPLE"
        :disabled="!!mapReason && !publicMap"
        :disabled-reason="mapReason"
        :recorded="recorded(state.public_map)"
      />
    </section>

    <section v-if="target === 'maintainer'" class="mt-10">
      <h2 class="text-h6 mb-2">The notice</h2>
      <v-btn
        variant="text"
        color="primary"
        size="large"
        class="ms-n4"
        :aria-expanded="noticeOpen"
        @click="toggleNotice"
      >
        Read the sharing notice (version {{ state.notice_version }})
      </v-btn>
      <v-alert v-if="noticeError" type="error" class="mb-2">{{ noticeError }}</v-alert>
      <EulaText v-else-if="noticeOpen && notice" :markdown="notice.markdown" />
      <v-progress-linear v-else-if="noticeOpen" indeterminate color="primary" />
      <v-checkbox
        v-if="noticeNeeded"
        v-model="noticeRead"
        label="I've read the notice"
        color="primary"
        hide-details
        class="mt-2"
      />
    </section>

    <v-alert v-if="error" type="error" class="mt-6">{{ error }}</v-alert>
    <div class="mt-8 d-flex flex-wrap align-center ga-4">
      <v-btn
        color="primary"
        size="large"
        :loading="saving"
        :disabled="saving || (noticeNeeded && !noticeRead)"
        @click="ask"
      >
        {{ firstRun ? 'Save and finish' : 'Save' }}
      </v-btn>
      <p v-if="done" role="status" class="text-body-1">Saved.</p>
    </div>

    <ConfirmDialog
      v-model="confirmOpen"
      title="Change the server?"
      text="Changing the server turns off the exact location and the public map. You can turn them on again for the new server."
      confirm-text="Change the server"
      confirm-color="primary"
      @confirm="save"
    />
  </div>
</template>

<style scoped>
/* Clear the app bar when a link (the Status page's "Check the token") scrolls to the section */
.token {
  scroll-margin-top: 80px;
}
</style>
