<!--
  A dialog with one text field, for a new hotspot name or password. The field shows what is typed, and there is no
  second field to type it again: the dialog is the confirmation, so it shows the value and the warning, and its
  button names the action ("Change password"). The button stays disabled until `rule` passes; the rule's message
  shows under the field once something is typed. `warning` may hold several paragraphs, split by a line break.
  Emits `save` with the value and closes.
-->
<script setup lang="ts">
import { computed, ref, watch } from 'vue'

const open = defineModel<boolean>({ required: true })
const props = defineProps<{
  title: string
  label: string
  warning: string
  rule: (value: string) => true | string
  confirmText: string
  initial?: string // what the field starts with, such as the current name
}>()
const emit = defineEmits<{ save: [value: string] }>()

const value = ref('')
watch(open, (isOpen) => {
  if (isOpen) value.value = props.initial ?? ''
})

const verdict = computed(() => props.rule(value.value))
const valid = computed(() => verdict.value === true)
const paragraphs = computed(() => props.warning.split('\n').filter(Boolean))

function save() {
  if (!valid.value) return
  emit('save', value.value)
  open.value = false
}
</script>

<template>
  <v-dialog v-model="open" max-width="440">
    <v-card color="surface" rounded="lg">
      <v-form @submit.prevent="save">
        <v-card-title class="text-h6 text-wrap pt-4">{{ title }}</v-card-title>
        <v-card-text>
          <p v-for="paragraph in paragraphs" :key="paragraph" class="text-body-1 mb-3">{{ paragraph }}</p>
          <v-text-field
            v-model="value"
            :label="label"
            type="text"
            autocomplete="off"
            autocapitalize="none"
            spellcheck="false"
            :error-messages="value && verdict !== true ? verdict : undefined"
            class="mt-2"
          />
        </v-card-text>
        <v-card-actions class="px-4 pb-4">
          <v-spacer />
          <v-btn variant="text" @click="open = false">Cancel</v-btn>
          <v-btn type="submit" color="primary" variant="flat" :disabled="!valid">{{ confirmText }}</v-btn>
        </v-card-actions>
      </v-form>
    </v-card>
  </v-dialog>
</template>
