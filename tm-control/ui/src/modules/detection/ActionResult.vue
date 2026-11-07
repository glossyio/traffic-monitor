<!-- One action's result on the Detection page. A use that Frigate hasn't come back from points to the Status page. -->
<script setup lang="ts">
export interface Result {
  type: 'info' | 'success' | 'warning' | 'error'
  text: string // unused when stalled
  stalled?: boolean
}

defineProps<{ result: Result }>()
</script>

<template>
  <v-alert :type="result.type" class="mt-2">
    <template v-if="result.stalled">
      Frigate hasn't come back yet; see the <router-link to="/status" class="text-decoration-underline">Status page</router-link>.
    </template>
    <template v-else>{{ result.text }}</template>
  </v-alert>
</template>
