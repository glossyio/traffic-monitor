<!--
  The parade, a small easter egg: a traffic cone at the end of the About page. A click opens a strip of road, one
  traveler crosses it every PASS_MS and the tally under the road counts it, a second click closes it. It asks for
  nothing and stores nothing; the tally lives only while the road is open.
-->
<script setup lang="ts">
import { mdiTrafficCone } from '@mdi/js'
import { onBeforeUnmount, reactive, ref } from 'vue'
import { PASS_MS, pickTraveler, tallyText, type Traveler } from './parade'

// `pick` is a prop so a test can send a chosen traveler instead of a random one
const props = withDefaults(defineProps<{ pick?: () => Traveler }>(), { pick: () => pickTraveler() })

const open = ref(false)
const counts = reactive<Record<string, number>>({})
const crossing = ref<Traveler | null>(null) // the one on the road now
const pass = ref(0) // a new key for each traveler, so the animation starts again from the left
const still = ref(false) // the browser asks for reduced motion: the traveler stays put, the tally still counts
let timer: ReturnType<typeof setInterval> | undefined

function send() {
  crossing.value = props.pick()
  pass.value++
}

// Each tick the traveler that just crossed is counted, and the next one starts
function tick() {
  if (crossing.value) counts[crossing.value.id] = (counts[crossing.value.id] ?? 0) + 1
  send()
}

function stop() {
  clearInterval(timer)
  timer = undefined
  crossing.value = null
}

function toggle() {
  if (open.value) {
    open.value = false
    stop()
    return
  }
  // matchMedia is missing in some old browsers and in the tests; then the road moves
  still.value = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches === true
  for (const id of Object.keys(counts)) delete counts[id]
  open.value = true
  send()
  timer = setInterval(tick, PASS_MS)
}

onBeforeUnmount(stop)
</script>

<template>
  <div class="mt-10">
    <v-btn
      icon
      variant="text"
      aria-label="Count some traffic"
      :aria-expanded="open ? 'true' : 'false'"
      @click="toggle"
    >
      <v-icon :icon="mdiTrafficCone" />
    </v-btn>

    <div v-if="open" class="mt-2">
      <v-sheet border rounded class="parade-road d-flex align-center justify-center">
        <v-icon
          v-if="crossing"
          :key="pass"
          :icon="crossing.icon"
          size="large"
          :class="still ? '' : 'moving'"
          :style="still ? '' : { animationDuration: `${PASS_MS}ms` }"
        />
      </v-sheet>
      <p class="text-body-2 text-medium-emphasis mt-2">{{ tallyText(counts) }}</p>
    </div>
  </div>
</template>

<style scoped>
/* The only custom CSS here: the road clips what is outside it, and a traveler slides from its left edge to its right */
.parade-road {
  position: relative;
  overflow: hidden;
  height: 56px;
}
.moving {
  position: absolute;
  animation-name: cross;
  animation-timing-function: linear;
  animation-fill-mode: forwards;
}
@keyframes cross {
  from {
    left: 0;
    transform: translateX(-100%);
  }
  to {
    left: 100%;
    transform: translateX(0);
  }
}
</style>
