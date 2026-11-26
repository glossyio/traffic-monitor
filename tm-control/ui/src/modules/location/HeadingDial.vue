<!--
  The heading dial: which way a sensor faces, in whole degrees clockwise from true north, 0 to 359, or null for Not
  set. A ring to tap or drag, the eight compass points as buttons around it (each gives its centre), a number field
  for an exact heading, and Not set. It is a plain input: `heading` in, `update:heading` out, nothing sent to the API.
  The README's "The heading dial" has the layout and the reasons.
-->
<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { POINTS, POINT_WORDS, angleAt, centreOf, facingWords, type Point } from './heading'

const props = defineProps<{ heading: number | null; label: string; disabled?: boolean }>()
const emit = defineEmits<{ 'update:heading': [heading: number | null] }>()

// The ring's drawing, in the SVG's own units, which are pixels: 200 square
const SIZE = 200
const CENTRE = SIZE / 2
const RING = 88
const TICK = 10
const NEEDLE = 76
// A press this close to the centre changes nothing: the angle there is noise
const HUB = 12

const MESSAGE = 'Enter a whole number from 0 to 359.'
const HELP =
  "North is up on a map. A phone's compass shows magnetic north unless it is set to true north. " +
  'If you only know the compass point, tap it.'

// Three rows, the ring in the middle one, so each point sits on its own line from the centre and Tab goes in
// reading order
const ROWS: (Point | 'ring')[][] = [
  ['nw', 'n', 'ne'],
  ['w', 'ring', 'e'],
  ['sw', 's', 'se'],
]

const labelId = useId()
const fieldId = useId()
const helpId = useId()

function pointName(point: Point): string {
  return `${point.toUpperCase()}, ${POINT_WORDS[point]}, ${centreOf(point)}°`
}

// The end of the needle and the ticks: `length` from the centre, towards `heading`
function towards(heading: number, length: number) {
  const radians = (heading * Math.PI) / 180
  return { x: CENTRE + length * Math.sin(radians), y: CENTRE - length * Math.cos(radians) }
}

const ticks = POINTS.map((point) => ({
  point,
  from: towards(centreOf(point), RING - TICK),
  to: towards(centreOf(point), RING),
}))
const tip = computed(() => (props.heading === null ? null : towards(props.heading, NEEDLE)))

// What the dial last showed or sent, so a drag that stays on one degree sends it once
const current = ref<number | null>(props.heading)

// The field's text and its message. It shows the heading, except while someone is typing a number that isn't one
// (then the message says why) or has emptied it on the way to the next (then it says nothing). Leaving the field puts
// it back in step with the heading.
const text = ref(props.heading === null ? '' : String(props.heading))
const message = ref('')
const typing = ref(false)

// What the live region says: only after a whole change, never at each step of a drag or while typing
const announced = ref('')
const dragging = ref(false)

watch(
  () => props.heading,
  (heading) => {
    current.value = heading
    if (parse(text.value) !== heading) {
      text.value = heading === null ? '' : String(heading)
      message.value = ''
    }
    if (!dragging.value && !typing.value) announced.value = facingWords(heading)
  },
)

// A whole number from 0 to 359 as typed, undefined for anything else (empty included)
function parse(value: string): number | undefined {
  const trimmed = value.trim()
  if (!/^\d{1,3}$/.test(trimmed)) return undefined
  const heading = Number(trimmed)
  return heading <= 359 ? heading : undefined
}

function send(heading: number | null) {
  if (heading === current.value) return
  current.value = heading
  emit('update:heading', heading)
}

// A point, Not set, or the ring: the field shows what was chosen, and any message goes
function choose(heading: number | null) {
  if (props.disabled) return
  text.value = heading === null ? '' : String(heading)
  message.value = ''
  send(heading)
}

function focusChanged(focused: boolean) {
  typing.value = focused
  if (focused) return
  text.value = props.heading === null ? '' : String(props.heading)
  message.value = ''
  announced.value = facingWords(props.heading) // a heading typed is said once the field is left
}

function typed(value: string) {
  text.value = value
  if (value.trim() === '') {
    message.value = ''
    return
  }
  const heading = parse(value)
  if (heading === undefined) {
    message.value = MESSAGE
    return
  }
  message.value = ''
  send(heading)
}

// The heading under the pointer, or null on the hub
function headingAt(event: PointerEvent): number | null {
  const box = (event.currentTarget as SVGSVGElement).getBoundingClientRect()
  const cx = box.left + box.width / 2
  const cy = box.top + box.height / 2
  if (Math.hypot(event.clientX - cx, event.clientY - cy) < HUB) return null
  return angleAt(event.clientX, event.clientY, cx, cy)
}

function press(event: PointerEvent) {
  if (props.disabled || event.button !== 0) return
  dragging.value = true
  // The drag keeps going when the pointer leaves the ring
  const ring = event.currentTarget as SVGSVGElement
  if (event.pointerId !== undefined) ring.setPointerCapture?.(event.pointerId)
  const heading = headingAt(event)
  if (heading !== null) choose(heading)
}

function move(event: PointerEvent) {
  if (!dragging.value || props.disabled) return
  const heading = headingAt(event)
  if (heading !== null) choose(heading)
}

function release() {
  if (!dragging.value) return
  dragging.value = false
  announced.value = facingWords(props.heading)
}

const describedBy = computed(() => (message.value ? `${fieldId}-messages ${helpId}` : helpId))
</script>

<template>
  <div role="group" :aria-labelledby="labelId">
    <div :id="labelId" class="text-body-1 mb-2">{{ label }}</div>
    <v-row>
      <v-col cols="12" sm="auto">
        <div class="d-inline-flex flex-column">
          <div v-for="(row, index) in ROWS" :key="index" class="d-flex justify-space-between align-center">
            <template v-for="item in row" :key="item">
              <svg
                v-if="item === 'ring'"
                :width="SIZE"
                :height="SIZE"
                :viewBox="`0 0 ${SIZE} ${SIZE}`"
                aria-hidden="true"
                :opacity="disabled ? 0.38 : undefined"
                :style="disabled ? undefined : { touchAction: 'none' }"
                @pointerdown="press"
                @pointermove="move"
                @pointerup="release"
                @pointercancel="release"
                @lostpointercapture="release"
              >
                <circle class="text-surface" fill="currentColor" :cx="CENTRE" :cy="CENTRE" :r="RING" />
                <g class="text-secondary" stroke="currentColor" fill="none" stroke-width="2">
                  <circle :cx="CENTRE" :cy="CENTRE" :r="RING" />
                  <line
                    v-for="tick in ticks"
                    :key="tick.point"
                    :x1="tick.from.x"
                    :y1="tick.from.y"
                    :x2="tick.to.x"
                    :y2="tick.to.y"
                  />
                </g>
                <line
                  v-if="tip"
                  data-needle
                  class="text-primary"
                  stroke="currentColor"
                  stroke-width="4"
                  stroke-linecap="round"
                  :x1="CENTRE"
                  :y1="CENTRE"
                  :x2="tip.x"
                  :y2="tip.y"
                />
                <circle
                  :class="tip ? 'text-primary' : 'text-secondary'"
                  fill="currentColor"
                  :cx="CENTRE"
                  :cy="CENTRE"
                  r="6"
                />
              </svg>
              <v-btn
                v-else
                icon
                :size="44"
                :variant="heading === centreOf(item) ? 'flat' : 'outlined'"
                :color="heading === centreOf(item) ? 'primary' : undefined"
                :aria-pressed="String(heading === centreOf(item))"
                :aria-label="pointName(item)"
                :disabled="disabled"
                @click="choose(centreOf(item))"
              >
                {{ item.toUpperCase() }}
              </v-btn>
            </template>
          </div>
        </div>
      </v-col>
      <v-col cols="12" sm>
        <p class="text-body-1 mb-4">{{ facingWords(heading) }}</p>
        <div class="d-flex flex-wrap align-start ga-3">
          <v-text-field
            :id="fieldId"
            :model-value="text"
            label="Degrees from north"
            inputmode="numeric"
            autocomplete="off"
            max-width="12rem"
            hide-details="auto"
            :error-messages="message ? [message] : []"
            :aria-describedby="describedBy"
            :disabled="disabled"
            @update:model-value="typed"
            @update:focused="focusChanged"
          />
          <v-btn
            size="large"
            :height="56"
            :variant="heading === null ? 'flat' : 'outlined'"
            :color="heading === null ? 'primary' : undefined"
            :aria-pressed="String(heading === null)"
            :disabled="disabled"
            @click="choose(null)"
          >
            Not set
          </v-btn>
        </div>
        <p :id="helpId" class="text-body-2 text-secondary mt-3">{{ HELP }}</p>
        <span class="d-sr-only" aria-live="polite">{{ announced }}</span>
      </v-col>
    </v-row>
  </div>
</template>
