<!--
  The Download your data card at the top of the Sharing page, for admins: the database's size, a box for the exact
  locations, and one Download button. The button asks first, in a question that says what the file holds. Unticked, it
  asks POST /sharing/download for a link to the database as it is stored (rounded locations); ticked, it asks
  POST /surveys/database-copy for the copy that holds the exact locations. Either answer is a link, which the browser
  opens (openDownload) and the device then makes the copy, which can take minutes.
  The tick, the error, and "started" are this card's own state: the page reads its state again after a save and after
  "I've reviewed this", and a new `facts` changes none of them. Once a download has started, Download and the box stay
  off until the page is reloaded, because each download makes a full copy of the database on the device.
-->
<script setup lang="ts">
import { computed, ref } from 'vue'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import { openDownload } from '../../components/download'
import ConfirmDialog from '../../components/ConfirmDialog.vue'
import StatusCard from '../../components/StatusCard.vue'
import { sizeWords } from './size'

type DownloadFacts = components['schemas']['DownloadFacts']

const props = defineProps<{ facts: DownloadFacts }>()

const SUBTITLE = "Save a copy of this device's database on the computer or phone you're using. Nothing is uploaded."

const WHAT_IT_HOLDS =
  "The file holds everything in this device's database: the events, radar readings, and air quality readings it recorded, its deployments, its watch log and setup history, and any comments."
const COPY_FIRST = 'The device makes a copy first, so the download can take a few minutes to start.'
const PLAIN_QUESTION = [
  WHAT_IT_HOLDS,
  "Each place's location is in it as the database stores it, rounded. The file holds no exact location, no pictures or video, and no passwords or tokens.",
  COPY_FIRST,
].join('\n')
// The warning is the one the Location page showed before the button moved here, word for word
const EXACT_QUESTION = [
  WHAT_IT_HOLDS,
  'This copy of the database includes the exact location of each place the device has been at. The database on this device keeps its rounded locations. Give the copy only to someone who should know where the device was.',
  'The file holds no pictures or video, and no passwords or tokens.',
  COPY_FIRST,
].join('\n')

const exact = ref(false) // unticked whenever the page opens
const asking = ref(false)
const sending = ref(false)
const error = ref('')
const started = ref<'' | 'plain' | 'exact'>('') // set once the request is answered; stays set until the page is reloaded

const canTick = computed(() => props.facts.exact_places > 0)
const items = computed(() =>
  props.facts.database_bytes === null ? [] : [{ label: 'Database size', value: sizeWords(props.facts.database_bytes) }],
)
const fileName = computed(() => (started.value === 'exact' ? 'tmdb-exact-locations.tar.gz' : 'tmdb.tar.gz'))

async function download() {
  const withExact = exact.value
  sending.value = true
  error.value = ''
  try {
    const { data } = withExact
      ? await api.POST('/api/v1/surveys/database-copy')
      : await api.POST('/api/v1/sharing/download')
    openDownload(data!.url)
    started.value = withExact ? 'exact' : 'plain'
  } catch (caught) {
    error.value = messageOf(caught)
  } finally {
    sending.value = false
  }
}
</script>

<template>
  <StatusCard title="Download your data" :subtitle="SUBTITLE" :items="items">
    <!-- Indented by the checkbox's width in the sentence under it, as a consent box's are -->
    <!-- A ticked box stays usable when the count drops to 0, so it can be unticked rather than stuck on -->
    <v-checkbox
      v-model="exact"
      :disabled="(!canTick && !exact) || started !== ''"
      color="primary"
      hide-details
      class="mt-4"
    >
      <template #label>
        <span class="text-subtitle-1 font-weight-medium">Include each place's exact location</span>
      </template>
    </v-checkbox>
    <p v-if="canTick" class="text-body-1 ms-10 mb-4">
      Without it, the file holds each place's location rounded, as the database stores it.
    </p>
    <p v-else class="text-body-1 ms-10 mb-4 font-weight-medium">
      No place this device has been at has an exact location yet.
    </p>
    <v-btn
      color="primary"
      variant="flat"
      size="large"
      :loading="sending"
      :disabled="sending || started !== ''"
      @click="asking = true"
    >
      Download
    </v-btn>
    <v-alert v-if="error" type="error" class="mt-4">{{ error }}</v-alert>
    <v-alert v-if="started" type="info" class="mt-4">
      The device is making a copy of the database. The download starts by itself when the copy is ready, which can take a
      few minutes for a large database. The file's name ends in {{ fileName }}.
    </v-alert>
    <!-- A download changes nothing on the device, so the question's button is the primary colour, not a warning one -->
    <ConfirmDialog
      v-model="asking"
      :title="exact ? 'Download the database with exact locations?' : 'Download the database?'"
      :text="exact ? EXACT_QUESTION : PLAIN_QUESTION"
      confirm-text="Download"
      confirm-color="primary"
      @confirm="download"
    />
  </StatusCard>
</template>
