<!--
  The running model's two object lists, as the card in use shows them in its fold: what Frigate tracks (the sentence),
  whether Frigate's list and the model's .json disagree, the objects the running model recognises with where that list
  came from, and the objects tracked on this device, in amber where the running model doesn't recognise them. When the
  recognised list isn't known, it says why instead. The card shows the amber chips outside the fold, from the same
  `notRecognised`.
-->
<script lang="ts">
import type { components } from '../../api/schema'

// The tracked objects the running model doesn't recognise; none when what it recognises isn't known
export function notRecognised({ recognised, tracked }: components['schemas']['LabelsOut']) {
  return recognised ? tracked.filter((label) => !recognised.includes(label)) : []
}
</script>

<script setup lang="ts">
import { computed } from 'vue'
import LabelChips from './LabelChips.vue'

type LabelsOut = components['schemas']['LabelsOut']

const props = defineProps<{
  labels: LabelsOut
  listsDiffer: boolean // Frigate's list against the .json of the model in use
  frigateAnswers: boolean
}>()

// Where the recognised list came from
const SOURCES = {
  frigate: 'As Frigate reports them.',
  sidecar: "From the model's .json, because Frigate didn't say.",
  labels_file: "From the installer's labels file, because Frigate didn't say.",
}

const unrecognised = computed(() => notRecognised(props.labels))
const recognisedTitle = computed(
  () => `Objects the running model recognises${props.labels.recognised ? ` (${props.labels.recognised.length})` : ''}`,
)
const trackedTitle = computed(
  () =>
    `Objects tracked on this device (${props.labels.tracked.length}` +
    `${unrecognised.value.length ? `, ${unrecognised.value.length} not recognised` : ''})`,
)
</script>

<template>
  <div>
    <p class="text-body-2 mb-3">Frigate tracks only the objects that are in both lists.</p>
    <p v-if="listsDiffer" class="text-body-2 mb-3">Frigate reports a different list than this model's .json.</p>
    <LabelChips
      v-if="labels.recognised"
      :title="recognisedTitle"
      :labels="labels.recognised"
      :marked="labels.tracked"
      marked-legend="Filled: tracked on this device."
    >
      <p v-if="labels.source" class="text-body-2 text-secondary mb-2">{{ SOURCES[labels.source] }}</p>
    </LabelChips>
    <section v-else>
      <h4 class="text-subtitle-1 font-weight-medium mb-2">{{ recognisedTitle }}</h4>
      <p class="text-body-2 text-secondary">
        {{
          frigateAnswers
            ? "The running model's labels aren't known."
            : "Frigate isn't answering, and the running model has no sidecar on the device."
        }}
      </p>
    </section>
    <LabelChips
      class="mt-4"
      :title="trackedTitle"
      :labels="labels.tracked"
      :flagged="unrecognised"
      flagged-legend="Amber: the running model doesn't recognise it."
    />
  </div>
</template>
