<!--
  One list of object labels, as chips under a small heading, with Copy, which puts them on the clipboard as
  comma-separated text ("person, bicycle, car") and says "Copied." for two seconds.
-->
<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { copyText } from '../../components/clipboard'

const props = defineProps<{ title: string; labels: string[] }>()

const result = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
onBeforeUnmount(() => clearTimeout(timer))

async function copy() {
  clearTimeout(timer)
  if (await copyText(props.labels.join(', '))) {
    result.value = 'Copied.'
    timer = setTimeout(() => (result.value = ''), 2000)
  } else {
    result.value = "This browser didn't let the page copy."
  }
}
</script>

<template>
  <section>
    <div class="d-flex flex-wrap align-center ga-3 mb-2">
      <h3 class="text-subtitle-1 font-weight-medium">{{ title }}</h3>
      <v-btn v-if="labels.length" variant="outlined" color="primary" min-height="44" @click="copy">Copy</v-btn>
      <span role="status" class="text-body-2 text-secondary">{{ result }}</span>
    </div>
    <div v-if="labels.length" class="d-flex flex-wrap ga-2">
      <v-chip v-for="(label, index) in labels" :key="index" size="small" variant="outlined">{{ label }}</v-chip>
    </div>
    <p v-else class="text-body-2 text-secondary">None.</p>
  </section>
</template>
