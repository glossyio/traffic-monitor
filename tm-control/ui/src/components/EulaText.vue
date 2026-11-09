<!-- The license agreement, in a box that scrolls on its own. -->
<script setup lang="ts">
import { marked } from 'marked'
import { computed } from 'vue'

const props = defineProps<{ markdown: string }>()

// The markdown is the EULA.md packaged with tm-control (GET /api/v1/setup/eula), never anything a user typed, so its
// HTML is shown as is. This is the app's only v-html.
const html = computed(() => marked.parse(props.markdown, { async: false }))
</script>

<template>
  <v-sheet border rounded="lg" color="surface" max-height="360" class="overflow-y-auto pa-4 text-body-1">
    <div class="eula" v-html="html" />
  </v-sheet>
</template>

<style scoped>
/* Vuetify's reset leaves headings and paragraphs unstyled and unspaced */
.eula :deep(h1),
.eula :deep(h2),
.eula :deep(h3) {
  font-size: 1.125rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
}
.eula :deep(p),
.eula :deep(ul),
.eula :deep(ol) {
  margin-bottom: 0.75rem;
}
.eula :deep(ul),
.eula :deep(ol) {
  padding-left: 1.5rem;
}
</style>
