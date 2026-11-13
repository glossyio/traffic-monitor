<!--
  Asks before something that can't be undone. The confirm button names the action, as in "Remove viewer", in the error
  colour unless the page says the action changes nothing. A line break in `text` starts a new paragraph.
-->
<script setup lang="ts">
import { computed } from 'vue'

const open = defineModel<boolean>({ required: true })
const props = defineProps<{
  title: string
  text: string
  confirmText: string
  confirmColor?: string
}>()
const emit = defineEmits<{ confirm: [] }>()

const paragraphs = computed(() => props.text.split('\n'))

// Emits before closing, so a parent that closes the dialog by clearing what it confirms still has it in the handler
function confirm() {
  emit('confirm')
  open.value = false
}
</script>

<template>
  <v-dialog v-model="open" max-width="440">
    <v-card color="surface" rounded="lg">
      <v-card-title class="text-h6 text-wrap pt-4">{{ title }}</v-card-title>
      <v-card-text class="text-body-1">
        <p v-for="(paragraph, index) in paragraphs" :key="index" :class="{ 'mb-3': index < paragraphs.length - 1 }">
          {{ paragraph }}
        </p>
      </v-card-text>
      <v-card-actions class="px-4 pb-4">
        <v-spacer />
        <v-btn variant="text" @click="open = false">Cancel</v-btn>
        <v-btn :color="confirmColor ?? 'error'" variant="flat" @click="confirm">{{ confirmText }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
