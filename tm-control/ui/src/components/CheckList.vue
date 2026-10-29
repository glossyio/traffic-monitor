<!--
  One group of the status report (GET /status): each check with its status mark, title, and the detail under it.
  A check's fix shows as the API words it: a link fix is a link at the end of the detail, a hint is a sentence after
  it, and for admins a restart fix is a button named for the unit ("Restart Frigate"). A group with any re-scan fix
  gets one "Re-scan hardware" button at its end. The list only says what was pressed; the page does the work and
  passes back `busy` and `notes`.
-->
<script setup lang="ts">
import { computed } from 'vue'
import type { components } from '../api/schema'
import { MARKS, type Note } from './status'

type Group = components['schemas']['Group']

const props = defineProps<{
  group: Group
  admin: boolean // viewers see the checks with no buttons
  busy: string | null // the unit restarting, or 'rescan', while its request runs
  notes?: Record<string, Note> // by unit, or 'rescan'; shown under that button
}>()
const emit = defineEmits<{ restart: [unit: string]; rescan: [] }>()

// A button for an admin to press: what it acts on (a unit, or 'rescan'), its words, and what it last said
interface Action {
  key: string
  text: string
  note?: Note
}

function action(key: string, text: string): Action {
  return { key, text, note: props.notes?.[key] }
}

const rows = computed(() =>
  props.group.checks.map((check) => {
    const fix = check.fix
    return {
      check,
      mark: MARKS[check.status],
      hint: fix?.kind === 'hint' ? fix.text : null,
      link: fix?.kind === 'link' && fix.href ? { to: fix.href, text: fix.text } : null,
      restart: props.admin && fix?.kind === 'restart' && fix.unit ? action(fix.unit, fix.text) : null,
    }
  }),
)

const rescan = computed(() => {
  const fix = props.group.checks.find((check) => check.fix?.kind === 'rescan')?.fix
  return props.admin && fix ? action('rescan', fix.text) : null
})

function press(key: string) {
  if (key === 'rescan') emit('rescan')
  else emit('restart', key)
}
</script>

<template>
  <section>
    <h2 class="text-h6 mb-1">{{ group.title }}</h2>
    <v-list bg-color="transparent" class="py-0">
      <v-list-item v-for="row in rows" :key="row.check.id" class="px-0 py-2">
        <!-- 4 px of room right and below: the list item hides overflow, which would cut off a button's focus ring -->
        <div class="d-flex ga-3 pe-1 pb-1">
          <v-icon :icon="row.mark.icon" :color="row.mark.color" class="flex-shrink-0" />
          <div class="flex-grow-1">
            <div class="text-body-1"><span class="d-sr-only">{{ row.mark.label }}: </span>{{ row.check.title }}</div>
            <div class="text-body-2 text-secondary">
              {{ row.check.detail }}
              <template v-if="row.hint">{{ row.hint }}</template>
              <router-link v-if="row.link" :to="row.link.to" class="text-primary">{{ row.link.text }}</router-link>
            </div>
            <div v-if="row.restart" class="d-flex flex-column align-end mt-2">
              <!-- the same button as the re-scan's below -->
              <v-btn
                variant="outlined"
                color="primary"
                min-height="44"
                :loading="busy === row.restart.key"
                :disabled="busy !== null && busy !== row.restart.key"
                @click="press(row.restart.key)"
              >
                {{ row.restart.text }}
              </v-btn>
              <v-alert v-if="row.restart.note?.error" type="error" density="compact" class="mt-2">
                {{ row.restart.note.text }}
              </v-alert>
              <p v-else-if="row.restart.note" class="text-body-2 mt-2">{{ row.restart.note.text }}</p>
            </div>
          </div>
        </div>
      </v-list-item>
    </v-list>

    <div v-if="rescan" class="d-flex flex-column align-end pe-1 pb-1 mt-2">
      <v-btn
        variant="outlined"
        color="primary"
        min-height="44"
        :loading="busy === rescan.key"
        :disabled="busy !== null && busy !== rescan.key"
        @click="press(rescan.key)"
      >
        {{ rescan.text }}
      </v-btn>
      <v-alert v-if="rescan.note?.error" type="error" density="compact" class="mt-2">{{ rescan.note.text }}</v-alert>
      <p v-else-if="rescan.note" class="text-body-2 mt-2">{{ rescan.note.text }}</p>
    </div>
  </section>
</template>
