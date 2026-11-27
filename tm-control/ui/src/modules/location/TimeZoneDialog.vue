<!--
  The dialog that sets the time zone of a used place or the place in use (PUT /surveys/{id}/timezone). It has the same
  control as the place form and the deploy review, TimeZonePick, started from the place's time zone, else the unit's
  clock's, so a place with none gets the clock's on Save. It never moves the unit, and it never sends null: with no
  time zone to show (no clock time zone, none chosen) Save waits for a choice. Saving the time zone the place already
  has is allowed, so a save that failed halfway can be finished, as Correct location allows the same point again.
  The dialog starts over each time it opens. Emits `saved` with the place the API answered with, then closes; and
  `stale` when the API refused because the place changed since the page loaded (409), or failed on the server (5xx,
  which can leave the time zone saved though the place's rows weren't corrected), so the page loads the places
  again. Any error stays beside the buttons and the dialog stays open.
-->
<script setup lang="ts">
import { ref, watch } from 'vue'
import { ApiError, api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import TimeZonePick from './TimeZonePick.vue'
import { startingTimeZone } from './timezones'

type SurveyOut = components['schemas']['SurveyOut']

const open = defineModel<boolean>('open', { required: true })
const props = defineProps<{
  place: SurveyOut // a used place or the place in use
  timeZones: string[] // the device's list of time zones, loaded once by the page; empty when it couldn't be
  timeZonesError: string // why the list couldn't be loaded; empty when it was
  clockTimeZone: string | null // the unit's clock's time zone; null when unknown
}>()
const emit = defineEmits<{ saved: [place: SurveyOut]; stale: [] }>()

const timeZone = ref<string | null>(null)
const openings = ref(0) // the control decides its box once, so each opening gives it a new key
const saving = ref(false)
const error = ref('')

watch(
  open,
  (isOpen) => {
    if (!isOpen) return
    timeZone.value = startingTimeZone(props.place.timezone, props.clockTimeZone)
    openings.value += 1
    error.value = ''
  },
  { immediate: true },
)

async function save() {
  if (timeZone.value === null) return
  saving.value = true
  error.value = ''
  try {
    const { data } = await api.PUT('/api/v1/surveys/{survey_id}/timezone', {
      params: { path: { survey_id: props.place.id } },
      body: { timezone: timeZone.value },
    })
    emit('saved', data as SurveyOut)
    open.value = false
  } catch (failure) {
    error.value = messageOf(failure)
    if (failure instanceof ApiError && (failure.status === 409 || failure.status >= 500)) emit('stale')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <v-dialog v-model="open" persistent max-width="560" aria-label="Time zone">
    <v-card color="surface" rounded="lg">
      <v-card-title class="text-h6 text-wrap pt-4">Time zone</v-card-title>
      <v-form @submit.prevent="save">
        <v-card-text>
          <p class="text-subtitle-1 font-weight-medium text-break">{{ place.description ?? 'No description' }}</p>
          <p class="text-body-2 text-secondary mb-4">{{ place.id }}</p>
          <p class="text-body-1 mb-6">
            Changing it corrects this place's stored deployments. It starts no new deployment.
          </p>
          <TimeZonePick
            :key="openings"
            v-model="timeZone"
            :time-zones="timeZones"
            :clock-time-zone="clockTimeZone"
            :error="timeZonesError"
            :disabled="saving"
          />
          <v-alert v-if="error" type="error" class="mt-4">{{ error }}</v-alert>
        </v-card-text>
        <v-card-actions class="px-4 pb-4">
          <v-spacer />
          <v-btn variant="text" min-height="44" :disabled="saving" @click="open = false">Cancel</v-btn>
          <v-btn
            type="submit"
            color="primary"
            variant="flat"
            min-height="44"
            :loading="saving"
            :disabled="timeZone === null"
          >
            Save
          </v-btn>
        </v-card-actions>
      </v-form>
    </v-card>
  </v-dialog>
</template>
