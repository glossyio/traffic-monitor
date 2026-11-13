<!--
  A section of the Network page that can be folded away: a bordered panel whose heading is a real <h2> holding the
  button that opens it (v-expansion-panel's title is a button with no heading around it, which would take "This
  device" and "Hotspot" out of a screen reader's list of headings). While it is folded the `summary` slot shows the
  one or two lines that matter; open, the content shows instead. `warning` is the accessible label of a small icon
  beside the title that marks a folded panel with something to read in it. The content stays mounted while folded, so
  what happens inside a panel (a job, its notice) goes on and the page can open the panel when there is news.
  The caller decides when it opens by itself; the person can always fold it again.
-->
<script setup lang="ts">
import { mdiAlertCircle, mdiChevronDown, mdiChevronUp } from '@mdi/js'

const open = defineModel<boolean>({ required: true })
defineProps<{ id: string; title: string; warning?: string }>()
</script>

<template>
  <section :id="id">
    <v-card variant="outlined" rounded="lg">
      <h2 class="text-h6">
        <v-btn
          block
          variant="text"
          size="large"
          class="justify-space-between text-none text-h6 px-4"
          :aria-expanded="open"
          :aria-controls="`${id}-body`"
          :append-icon="open ? mdiChevronUp : mdiChevronDown"
          @click="open = !open"
        >
          <span class="d-flex align-center ga-2">
            {{ title }}
            <v-icon v-if="warning && !open" :icon="mdiAlertCircle" color="warning" role="img" :aria-label="warning" />
          </span>
        </v-btn>
      </h2>
      <div v-if="!open" :id="`${id}-summary`" class="px-4 pb-4">
        <slot name="summary" />
      </div>
      <v-expand-transition>
        <div v-show="open" :id="`${id}-body`" class="px-4 pb-4">
          <slot />
        </div>
      </v-expand-transition>
    </v-card>
  </section>
</template>
