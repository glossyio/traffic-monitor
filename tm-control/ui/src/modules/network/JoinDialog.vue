<!--
  The dialog an admin gets from Join on a nearby network: what the unit will do to its radio, the unit's Wi-Fi MAC
  address (a network that only admits listed devices needs it on its list first), and the password. What happens
  depends on where the radio is now: on the unit's hotspot it goes away for the test and a phone on it must rejoin by
  hand; on another network the unit leaves it for the test; otherwise there is nothing to lose. The field shows what
  is typed and there is no second one, as for the hotspot's password. A saved network offers its saved password
  first. Emits `join` with the typed password, or null for the saved one, and closes.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { components } from '../../api/schema'
import FactRow from './FactRow.vue'
import { wifiPasswordRule } from './rules'

type Nearby = components['schemas']['Nearby']
type Wifi = components['schemas']['Wifi']
type HotspotState = components['schemas']['HotspotState']

const open = defineModel<boolean>({ required: true })
const props = defineProps<{
  network: Nearby
  mac: string | null
  wifi: Wifi
  hotspot: HotspotState | null
  onHotspot: boolean
}>()
const emit = defineEmits<{ join: [password: string | null] }>()

const password = ref('')
const typing = ref(false) // for a saved network: the field is shown only after "Enter a new password"
watch(
  open,
  (isOpen) => {
    if (isOpen) {
      password.value = ''
      typing.value = !props.network.saved
    }
  },
  { immediate: true },
)

const verdict = computed(() => wifiPasswordRule(password.value))
const ready = computed(() => !typing.value || verdict.value === true)

// What will happen, by where the radio is: a paragraph for the test, one for what a phone must do, one for the switch
const plan = computed(() => {
  const name = props.network.name
  const joins = `If the test passes, the unit joins ${name} 5 minutes later, or when you tap Switch now`
  if (props.wifi.mode === 'hotspot') {
    const hotspot = props.hotspot?.name ?? 'the hotspot'
    return [
      `The unit tests ${name} first. Its hotspot is away for up to a minute, then comes back with the result.`,
      `A phone on the hotspot must rejoin ${hotspot} by hand to see it.`,
      `${joins}, and the hotspot stops.`,
    ]
  }
  if (props.wifi.mode === 'network') {
    const current = props.wifi.network || 'its network'
    return [
      `The unit tests ${name} first. It leaves ${current} for up to a minute, then comes back with the result.`,
      `${joins}.`,
    ]
  }
  return [`The unit tests ${name} first, which takes up to a minute. ${joins}.`]
})

function submit() {
  if (!ready.value) return
  emit('join', typing.value ? password.value : null)
  open.value = false
}
</script>

<template>
  <v-dialog v-model="open" max-width="440">
    <v-card color="surface" rounded="lg">
      <v-form @submit.prevent="submit">
        <v-card-title class="text-h6 text-wrap pt-4">Join {{ network.name }}</v-card-title>
        <v-card-text>
          <p v-for="paragraph in plan" :key="paragraph" class="text-body-1 mb-3">{{ paragraph }}</p>
          <p v-if="onHotspot" class="text-body-1 mb-3">
            You're on the hotspot now, so this page stops answering during the test.
          </p>

          <FactRow v-if="mac" label="The unit's Wi-Fi MAC address" :value="mac" copy="Wi-Fi MAC address" class="mb-1" />
          <p v-if="mac" class="text-body-2 text-secondary mb-4">
            A network that only admits listed devices needs this address on its list first.
          </p>

          <template v-if="typing">
            <v-text-field
              v-model="password"
              :label="`Password for ${network.name}`"
              type="text"
              autocomplete="off"
              autocapitalize="off"
              spellcheck="false"
              :error-messages="password && verdict !== true ? verdict : undefined"
              class="mt-2"
            />
          </template>
          <template v-else>
            <p class="text-body-1">Uses the saved password.</p>
            <v-btn variant="text" color="primary" size="large" class="ms-n4" @click="typing = true">
              Enter a new password
            </v-btn>
          </template>
        </v-card-text>
        <v-card-actions class="px-4 pb-4">
          <v-spacer />
          <v-btn variant="text" @click="open = false">Cancel</v-btn>
          <v-btn type="submit" color="primary" variant="flat" :disabled="!ready">Test and join</v-btn>
        </v-card-actions>
      </v-form>
    </v-card>
  </v-dialog>
</template>
