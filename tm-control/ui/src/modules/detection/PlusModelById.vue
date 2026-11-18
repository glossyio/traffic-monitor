<!--
  The form that uses a Frigate+ model by its ID: a field for the ID, which the page's confirmation then asks about, and
  the button. A pasted `plus://` address works too, since Frigate+ shows models that way. The page keeps the state and
  the action; the form only emits the cleaned ID, and is disabled while any action runs or Frigate downloads a model.
  `result` is the answer to the last try, shown under the button.
-->
<script lang="ts">
const ID = /^[0-9a-f]{32}$/

// What was typed or pasted as a model ID: trimmed, without one leading plus://, and null when it isn't an ID
export function cleanId(typed: string): string | null {
  const text = typed.trim()
  const id = text.startsWith('plus://') ? text.slice('plus://'.length) : text
  return ID.test(id) ? id : null
}
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'
import ActionResult, { type Result } from './ActionResult.vue'

defineProps<{ disabled: boolean; downloading: boolean; result: Result | null }>()
const emit = defineEmits<{ use: [id: string] }>()

const typed = ref('')
const id = computed(() => cleanId(typed.value))
const wrong = computed(() => (typed.value.trim() && !id.value ? 'A model ID is 32 characters, each 0-9 or a-f.' : ''))

function submit() {
  if (id.value) emit('use', id.value)
}
</script>

<template>
  <div>
    <p class="text-body-1 mb-4">
      Copy the model's ID from your models on the Frigate+ website. Frigate downloads the model with the API key, then
      restarts.
    </p>
    <v-form @submit.prevent="submit">
      <v-text-field
        v-model="typed"
        label="Model ID"
        autocomplete="off"
        autocapitalize="off"
        spellcheck="false"
        :error-messages="wrong"
        :disabled="disabled || downloading"
        class="mb-2"
      />
      <v-btn type="submit" color="primary" size="large" :disabled="disabled || downloading || !id">
        Download and use
      </v-btn>
    </v-form>
    <v-alert v-if="downloading" type="info" class="mt-4">
      Frigate is downloading the model. This can take a few minutes. You can leave this page.
    </v-alert>
    <ActionResult v-if="result" :result="result" />
  </div>
</template>
