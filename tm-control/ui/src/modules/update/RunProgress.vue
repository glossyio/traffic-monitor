<!--
  An update's stages (the run's `stages`, in the state file's order), each with its title and a mark: done, running,
  failed, or stopped (an attempt a restart cut off). While the run goes on, the stages a run of this version still goes
  through after the current one follow as not started, and the page says it can be closed. When the device stops
  answering (`lost`), an info notice says that is expected; the last stages stay.
-->
<script setup lang="ts">
import { mdiCircleOutline } from '@mdi/js'
import { computed } from 'vue'
import { MARKS } from '../../components/status'
import type { Run } from './update'
import { STAGE_ORDER, stageTitle } from './words'

const props = defineProps<{ run: Run; lost: boolean }>()

type RowState = 'done' | 'running' | 'failed' | 'stopped' | 'waiting'

interface Row {
  key: string
  title: string
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
    if (!stage.finished_at) {
      if (index < last) state = 'stopped' // a restart cut it off, and the stage began again
      else if (running.value) state = 'running'
      else state = props.run.status === 'failed' ? 'failed' : 'stopped'
    }
    return { key: `${index}-${stage.id}`, title: stageTitle(stage.id), state }
  })
  if (!running.value) return drawn

  // The stages still to come, when this version knows the current one
  const at = STAGE_ORDER.indexOf(props.run.stage ?? '')
  if (at === -1) return drawn
  const seen = new Set(stages.map((stage) => stage.id))
  const upcoming = STAGE_ORDER.slice(at + 1)
    .filter((id) => !seen.has(id))
    .map((id): Row => ({ key: `next-${id}`, title: stageTitle(id), state: 'waiting' }))
  return [...drawn, ...upcoming]
})
</script>

<template>
  <div>
    <v-alert v-if="lost" type="info" variant="tonal" class="mb-4">
      The device isn't answering. That is expected for a few minutes while it switches or restarts. This page keeps
      trying.
    </v-alert>

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
          </span>
        </div>
      </v-list-item>
    </v-list>

    <p v-if="running" class="text-body-1 mt-4">You can close this page. The update carries on.</p>
  </div>
</template>
