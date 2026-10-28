<!-- Asks before something that can't be undone. The confirm button names the action, as in "Remove viewer". -->
<script setup lang="ts">
const open = defineModel<boolean>({ required: true })
defineProps<{
  title: string
  text: string
  confirmText: string
}>()
const emit = defineEmits<{ confirm: [] }>()

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
      <v-card-text class="text-body-1">{{ text }}</v-card-text>
      <v-card-actions class="px-4 pb-4">
        <v-spacer />
        <v-btn variant="text" @click="open = false">Cancel</v-btn>
        <v-btn color="error" variant="flat" @click="confirm">{{ confirmText }}</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
