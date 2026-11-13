<!--
  One fact as the Network page shows it: a small label above the value, then the value with its Copy button and
  anything else the row needs (`actions`) on the same line. With `copy`, the Copy button reads "Copy <copy>". The
  value wraps rather than push the buttons off a phone's screen. The caller sets the spacing around the row.
-->
<script setup lang="ts">
import CopyButton from '../../components/CopyButton.vue'

defineProps<{ label: string; value?: string; copy?: string }>()
</script>

<template>
  <div>
    <div class="text-body-2 text-secondary">{{ label }}</div>
    <div class="d-flex flex-wrap align-center">
      <span class="text-body-1 text-break"><slot>{{ value }}</slot></span>
      <CopyButton v-if="copy && value" :text="value" :label="copy" />
      <slot name="actions" />
    </div>
  </div>
</template>
