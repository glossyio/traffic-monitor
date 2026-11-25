<!--
  The side view of a mounted sensor: the road, the support with the unit on it at its height, the line of sight down
  to the centre of the view, and the three values beside their parts. It draws the three values it is given and works
  none out; the page passes the API's values. The README's "Lengths and the side view" has the layout and the reasons.
-->
<script setup lang="ts">
import { computed } from 'vue'
import { shown, type Unit } from './lengths'

const props = defineProps<{
  heightM: number | null
  pitchDeg: number | null
  distanceM: number | null
  unit: Unit
}>()

// The drawing, in the SVG's own units, which are pixels
const WIDTH = 300
const HEIGHT = 180
const POLE_X = 64
const GROUND = 130
const TOP = 26
const RIGHT = 284
const DASH = '6 4'

function length(metres: number): string {
  return `${shown(metres, props.unit)} ${props.unit}`
}

function degrees(value: number): string {
  return `${Number(value.toFixed(1))}°`
}

// One scale for both directions, so the support and the ground point both fit. A missing distance asks for no room.
const scale = computed(() => {
  const height = props.heightM ?? 0
  const down = (GROUND - TOP) / height
  const distance = props.distanceM
  return distance === null || distance <= 0 ? down : Math.min(down, (RIGHT - POLE_X) / distance)
})

const top = computed(() => GROUND - (props.heightM ?? 0) * scale.value)
const groundX = computed(() => (props.distanceM === null ? null : POLE_X + props.distanceM * scale.value))

// Where the line of sight ends. At the ground point when the distance is given; along the tilt, to the edge or the
// ground, when only the tilt is; a stand-in, dashed, when neither is.
const sight = computed(() => {
  const x1 = POLE_X
  const y1 = top.value
  if (groundX.value !== null) return { x1, y1, x2: groundX.value, y2: GROUND }
  if (props.pitchDeg === null) return { x1, y1, x2: POLE_X + (RIGHT - POLE_X) * 0.6, y2: GROUND }
  if (props.pitchDeg >= 90) return { x1, y1, x2: x1, y2: GROUND }
  const radians = (props.pitchDeg * Math.PI) / 180
  const reach = Math.min((RIGHT - POLE_X) / Math.cos(radians), (GROUND - y1) / Math.sin(radians))
  return { x1, y1, x2: x1 + reach * Math.cos(radians), y2: y1 + reach * Math.sin(radians) }
})

// Beside the middle of the support, and above the road when the support is too short to hold the label
const heightLabelY = computed(() => Math.min((top.value + GROUND) / 2 + 4, GROUND - 8))

const alternative = computed(() => {
  const parts = [`Side view. The unit is ${length(props.heightM ?? 0)} above the road.`]
  parts.push(props.pitchDeg === null ? 'Its tilt is not set.' : `Its tilt is ${degrees(props.pitchDeg)} below level.`)
  parts.push(
    props.distanceM === null
      ? 'The distance to the centre of its view is not set.'
      : `The centre of its view is ${length(props.distanceM)} along the ground.`,
  )
  return parts.join(' ')
})
</script>

<template>
  <p v-if="heightM === null || heightM <= 0" class="text-body-2 text-secondary">Enter the height to see the side view.</p>
  <svg
    v-else
    :width="WIDTH"
    :height="HEIGHT"
    :viewBox="`0 0 ${WIDTH} ${HEIGHT}`"
    role="img"
    :aria-label="alternative"
  >
    <g class="text-secondary" stroke="currentColor" fill="none">
      <line :x1="8" :y1="GROUND" :x2="WIDTH - 8" :y2="GROUND" stroke-width="2" />
      <line :x1="POLE_X" :y1="top" :x2="POLE_X" :y2="GROUND" stroke-width="4" />
      <template v-if="groundX !== null">
        <line :x1="POLE_X" :y1="GROUND + 14" :x2="groundX" :y2="GROUND + 14" stroke-width="1" />
        <line :x1="POLE_X" :y1="GROUND + 10" :x2="POLE_X" :y2="GROUND + 18" stroke-width="1" />
        <line :x1="groundX" :y1="GROUND + 10" :x2="groundX" :y2="GROUND + 18" stroke-width="1" />
      </template>
      <line v-else :x1="POLE_X" :y1="GROUND + 14" :x2="RIGHT" :y2="GROUND + 14" stroke-width="1" :stroke-dasharray="DASH" />
    </g>
    <line
      data-sight
      class="text-primary"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      :stroke-dasharray="pitchDeg === null ? DASH : undefined"
      :x1="sight.x1"
      :y1="sight.y1"
      :x2="sight.x2"
      :y2="sight.y2"
    />
    <circle v-if="groundX !== null" class="text-primary" fill="currentColor" :cx="groundX" :cy="GROUND" r="4" />
    <rect class="text-primary" fill="currentColor" :x="POLE_X - 8" :y="top - 6" width="16" height="12" rx="2" />
    <text :x="POLE_X - 10" :y="heightLabelY" text-anchor="end" font-size="12" fill="currentColor">
      {{ length(heightM) }}
    </text>
    <text v-if="pitchDeg !== null" :x="POLE_X + 12" :y="top - 8" font-size="12" fill="currentColor">
      {{ degrees(pitchDeg) }}
    </text>
    <text
      v-if="groundX !== null && distanceM !== null"
      :x="(POLE_X + groundX) / 2"
      :y="GROUND + 32"
      text-anchor="middle"
      font-size="12"
      fill="currentColor"
    >
      {{ length(distanceM) }}
    </text>
  </svg>
</template>
