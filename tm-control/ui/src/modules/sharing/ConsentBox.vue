<!--
  One sharing choice: a checkbox with a title, a sentence on what it does, and "See an example", which shows what is
  sent as it would reach the server. The box is never ticked unless the parent says so (v-model). When it can't be
  ticked, `disabledReason` says why in plain words. `recorded` is the choice as the device last recorded it: when it
  is on, the box says since when. Withdrawing is the same box, unticked and saved on the page it was given.
-->
<script setup lang="ts">
import { ref } from 'vue'
import type { components } from '../../api/schema'
import { agoAt } from '../../components/relative-time'

type ConsentOut = components['schemas']['ConsentOut']

const checked = defineModel<boolean>({ required: true })
defineProps<{
  title: string
  text: string
  example: string
  disabled?: boolean
  disabledReason?: string
  recorded: ConsentOut
}>()

const exampleOpen = ref(false)
</script>

<template>
  <div>
    <v-checkbox v-model="checked" :disabled="disabled" color="primary" hide-details>
      <template #label>
        <span class="text-subtitle-1 font-weight-medium">{{ title }}</span>
      </template>
    </v-checkbox>
    <!-- Indented by the checkbox's width, so the sentences line up under the title -->
    <div class="ms-10">
      <p class="text-body-1">{{ text }}</p>
      <p v-if="disabled && disabledReason" class="text-body-1 mt-1 font-weight-medium">{{ disabledReason }}</p>
      <p v-if="recorded.granted" class="text-body-2 text-secondary mt-1">
        {{ recorded.at ? `On since ${agoAt(recorded.at)}` : 'On' }}
      </p>
      <v-btn
        variant="text"
        color="primary"
        size="large"
        class="ms-n4"
        :aria-expanded="exampleOpen"
        @click="exampleOpen = !exampleOpen"
      >
        {{ exampleOpen ? 'Hide the example' : 'See an example' }}
      </v-btn>
      <v-sheet v-if="exampleOpen" border rounded="lg" color="surface" class="pa-4 overflow-x-auto">
        <pre class="text-body-2">{{ example }}</pre>
      </v-sheet>
    </div>
  </div>
</template>
