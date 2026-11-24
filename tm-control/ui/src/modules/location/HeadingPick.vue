<!--
  The one pick for which way a sensor faces: the eight compass points and Not set, over a heading in whole degrees.
  `v-model` is the heading (null for Not set). Choosing a point gives its centre, 0, 45, ... 315. A measured heading
  that is not a centre, such as 40 from an app or a CSV, is listed first as "NE (40°)" and kept as it is until
  another is chosen, so opening a pick never changes it. It stays listed after a point is chosen, so it can be chosen
  again: the pick remembers the last such heading it was given for as long as it is mounted. A user that reuses one
  pick for another place or deployment gives it a `:key` that names it, so one place's heading isn't offered for
  another. The Location page's three places that choose a heading (the place form, the deploy review, the
  correction) use it.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { headingChoices } from './heading'

const heading = defineModel<number | null>({ required: true })
defineProps<{
  label?: string
  ariaLabel?: string
  density?: 'default' | 'comfortable' | 'compact'
  disabled?: boolean
}>()

// The last heading given that isn't a centre, so it stays choosable after a point is chosen
const measured = ref<number | null>(null)
watch(
  heading,
  (value) => {
    if (value !== null && value % 45 !== 0) measured.value = value
  },
  { immediate: true },
)

const choices = computed(() => headingChoices(measured.value ?? heading.value))
</script>

<template>
  <v-select
    v-model="heading"
    :items="choices"
    :label="label"
    :aria-label="ariaLabel"
    :density="density"
    :disabled="disabled"
    variant="outlined"
    hide-details
  />
</template>
