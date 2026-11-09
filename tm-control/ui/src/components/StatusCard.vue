<!--
  A card that names a thing and lists facts about it, label above value: the device card on the home page and the
  Device page. A fact with `progress` (the share used, 0 to 100, such as the storage's) gets a thin bar under its
  value and a row of its own. Anything in the default slot goes at the bottom of the card.
-->
<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  title: string
  subtitle?: string | string[] // one line under the title, or several
  items: { label: string; value: string; progress?: number }[]
}>()

const subtitles = computed(() => (props.subtitle === undefined ? [] : [props.subtitle].flat()))
</script>

<template>
  <v-card color="surface" variant="flat" rounded="lg" class="pa-2">
    <v-card-item>
      <h2 class="text-h5 text-sm-h4 font-weight-medium text-break">{{ title }}</h2>
      <p v-for="line in subtitles" :key="line" class="text-body-1 text-secondary mt-1">{{ line }}</p>
    </v-card-item>
    <v-card-text>
      <v-row dense>
        <v-col v-for="item in items" :key="item.label" cols="12" :sm="item.progress === undefined ? 6 : 12">
          <div class="text-body-2 text-secondary">{{ item.label }}</div>
          <div class="text-body-1 text-break">{{ item.value }}</div>
          <v-progress-linear
            v-if="item.progress !== undefined"
            :model-value="item.progress"
            :aria-label="`${item.label}: ${item.progress}% used`"
            color="primary"
            bg-color="secondary"
            height="6"
            rounded
            class="mt-2"
          />
        </v-col>
      </v-row>
      <slot />
    </v-card-text>
  </v-card>
</template>
