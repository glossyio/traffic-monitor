<!--
  An icon button that copies `text` (a name, an address) and shows a check for two seconds. `label` says what it
  copies, so the button reads "Copy <label>" to a screen reader. When the browser refuses, a line beside it asks the
  person to select the text instead.
-->
<script setup lang="ts">
import { mdiCheck, mdiContentCopy } from '@mdi/js'
import { onBeforeUnmount, ref } from 'vue'
import { copyText } from './clipboard'

const props = defineProps<{ text: string; label: string }>()

const copied = ref(false)
const refused = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined

async function copy() {
  refused.value = false
  if (await copyText(props.text)) {
    copied.value = true
    clearTimeout(timer)
    timer = setTimeout(() => (copied.value = false), 2000)
  } else {
    copied.value = false
    refused.value = true
  }
}

onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <span class="d-inline-flex align-center">
    <v-btn
      :icon="copied ? mdiCheck : mdiContentCopy"
      :aria-label="`Copy ${label}`"
      :color="copied ? 'success' : undefined"
      variant="text"
      density="comfortable"
      @click="copy"
    />
    <span v-if="refused" class="text-body-2 text-secondary">Select the text to copy it.</span>
  </span>
</template>
