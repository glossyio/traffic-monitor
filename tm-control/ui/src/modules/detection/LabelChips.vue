<!--
  One list of object labels, as chips, under a small heading when it has a title, with Copy, which puts them on the clipboard as
  comma-separated text ("person, bicycle, car") and says "Copied." for two seconds. A label in `marked` is filled and
  one in `flagged` is amber, which wins over filled. A mark's legend shows only when a chip has that mark, so colour is
  never the only cue.
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { copyText } from '../../components/clipboard'

const props = defineProps<{
  title?: string
  labels: string[]
  marked?: string[]
  flagged?: string[]
  markedLegend?: string
  flaggedLegend?: string
}>()

const isFlagged = (label: string) => !!props.flagged?.includes(label)
const isMarked = (label: string) => !isFlagged(label) && !!props.marked?.includes(label)
const look = (label: string) => {
  if (isFlagged(label)) return { variant: 'outlined', color: 'warning' } as const
  return isMarked(label) ? ({ variant: 'tonal', color: 'primary' } as const) : ({ variant: 'outlined' } as const)
}
const showMarkedLegend = computed(() => !!props.markedLegend && props.labels.some(isMarked))
const showFlaggedLegend = computed(() => !!props.flaggedLegend && props.labels.some(isFlagged))

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
      <h4 v-if="title" class="text-subtitle-1 font-weight-medium">{{ title }}</h4>
      <v-btn v-if="labels.length" variant="outlined" color="primary" min-height="44" @click="copy">Copy</v-btn>
      <span role="status" class="text-body-2 text-secondary">{{ result }}</span>
    </div>
    <div v-if="labels.length" class="d-flex flex-wrap ga-2">
      <v-chip v-for="(label, index) in labels" :key="index" size="small" v-bind="look(label)">{{ label }}</v-chip>
    </div>
    <p v-else class="text-body-2 text-secondary">None.</p>
    <p v-if="showMarkedLegend" class="text-body-2 text-secondary mt-2">{{ markedLegend }}</p>
    <p v-if="showFlaggedLegend" class="text-body-2 text-secondary mt-2">{{ flaggedLegend }}</p>
  </section>
</template>
