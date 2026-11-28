<!--
  An update's stages (the run's `stages`, in the state file's order), each with its title and a mark: done, running,
  failed, or stopped (an attempt a restart cut off). A failed run's last row is the failed one, whatever its finish
  time: both writers give it one. While the run goes on, the stages a run of this version still goes through after the
  current one follow as not started. The switch and restart rows carry a note that the device stops answering, in every
  state, so the silence is no surprise. Only the list: the page around it says the rest.
-->
<script setup lang="ts">
import { mdiCircleOutline } from '@mdi/js'
import { computed } from 'vue'
import { MARKS } from '../../components/status'
import type { Run } from './update'
import { STAGE_ORDER, stageNote, stageTitle } from './words'

const props = defineProps<{ run: Run }>()

type RowState = 'done' | 'running' | 'failed' | 'stopped' | 'waiting'

interface Row {
  key: string
  title: string
  note: string | null
  state: RowState
}

// The mark for each state, in the Status page's shapes and colors where there is one
const LOOK: Record<RowState, { icon: string | null; color: string; label: string }> = {
  done: { icon: MARKS.ok.icon, color: MARKS.ok.color, label: 'Done' },
  running: { icon: null, color: 'primary', label: 'Running' }, // a spinner
  failed: { icon: MARKS.error.icon, color: MARKS.error.color, label: 'Failed' },
  stopped: { icon: MARKS.warn.icon, color: MARKS.warn.color, label: 'Stopped' },
  waiting: { icon: mdiCircleOutline, color: 'secondary', label: 'Not started' },
}

const running = computed(() => props.run.status === 'running')

const rows = computed<Row[]>(() => {
  const stages = props.run.stages
  const last = stages.length - 1
  const drawn = stages.map((stage, index): Row => {
    let state: RowState = 'done'
    if (index === last && props.run.status === 'failed') state = 'failed'
    else if (!stage.finished_at) {
      if (index < last) state = 'stopped' // a restart cut it off, and the stage began again
      else state = running.value ? 'running' : 'stopped' // stopped: interrupted, or cut off in the switch
    }
    return { key: `${index}-${stage.id}`, title: stageTitle(stage.id), note: stageNote(stage.id), state }
  })
  if (!running.value) return drawn

  // The stages still to come, when this version knows the current one (in a restart, the ones after the switch)
  const current = props.run.stage === 'reboot' ? 'switch' : (props.run.stage ?? '')
  const at = STAGE_ORDER.indexOf(current)
  if (at === -1) return drawn
  const seen = new Set(stages.map((stage) => stage.id))
  const upcoming = STAGE_ORDER.slice(at + 1)
    .filter((id) => !seen.has(id))
    .map((id): Row => ({ key: `next-${id}`, title: stageTitle(id), note: stageNote(id), state: 'waiting' }))
  return [...drawn, ...upcoming]
})
</script>

<template>
  <v-list v-if="rows.length" bg-color="transparent" class="py-0">
    <v-list-item v-for="row in rows" :key="row.key" class="px-0" min-height="40" :data-stage="row.key">
      <div class="d-flex align-center ga-3">
        <v-progress-circular
          v-if="row.state === 'running'"
          indeterminate
          size="24"
          width="3"
          :color="LOOK.running.color"
          class="flex-shrink-0"
        />
        <v-icon v-else :icon="LOOK[row.state].icon!" :color="LOOK[row.state].color" class="flex-shrink-0" />
        <span class="text-body-1" :class="{ 'text-secondary': row.state === 'waiting' }">
          <span class="d-sr-only">{{ LOOK[row.state].label }}: </span>{{ row.title }}
          <span v-if="row.note" class="text-secondary">{{ row.note }}</span>
        </span>
      </div>
    </v-list-item>
  </v-list>
</template>
