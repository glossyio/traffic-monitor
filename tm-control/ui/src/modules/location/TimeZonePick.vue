<!--
  The one control for a place's time zone, used by the place form, the deploy review, and the Time zone dialog. The
  `v-model` is the time zone's name (null only while there is none to show, and the control never sends null on its
  own). Most places are in the unit's clock's time zone, so it says so in a line and has one box, "This place is in a
  different time zone". Ticking opens the list, starting at the same time zone, and unticking puts the clock's back.
  With no clock time zone (null) there is no line and no box: the list shows at once.
  Whether the box is ticked is decided once, when the control mounts: ticked when there is no clock time zone or the
  model differs from it. A parent that starts over (another place, a reset form) gives it a new `:key`, so it decides
  again. `timeZones` is the device's list, which the page loads once for every control. When it couldn't be loaded,
  `error` takes the hint's place and disables the list, and the box still works. `disabled` disables both. Emptying
  the list's text changes nothing: the control keeps the last name and never emits null or an empty name.
-->
<script setup lang="ts">
import { nextTick, ref } from 'vue'

const model = defineModel<string | null>({ required: true })
const props = defineProps<{
  timeZones: string[]
  clockTimeZone: string | null
  error?: string
  disabled?: boolean
}>()

const HINT = "Recorded with this place's data, also when no location is stored."

const different = ref(props.clockTimeZone === null || model.value !== props.clockTimeZone)

function setDifferent(on: boolean | null) {
  different.value = !!on
  if (!on) model.value = props.clockTimeZone
}

// The list's model, except that it never hands up an empty one: Vuetify clears a single list's model when its text is
// emptied, and that would send null (or '') up as a choice. The name stays; it shows again when the list loses focus.
function pick(name: string | null) {
  if (name) model.value = name
}

// When the list gets focus its text is selected, so typing "Berlin" replaces the name instead of landing in the
// middle of it, as on the Date and time page.
function selectText(event: FocusEvent) {
  const input = event.target
  if (input instanceof HTMLInputElement) void nextTick(() => input.select())
}
</script>

<template>
  <div>
    <div class="text-body-2 text-secondary">Time zone</div>
    <template v-if="clockTimeZone !== null">
      <p v-if="!different" class="text-body-1">{{ model ?? clockTimeZone }}, the same as the unit's clock</p>
      <v-checkbox
        :model-value="different"
        label="This place is in a different time zone"
        color="primary"
        hide-details
        :disabled="disabled"
        @update:model-value="setDifferent"
      />
    </template>
    <v-autocomplete
      v-if="different"
      :model-value="model"
      :items="timeZones"
      label="Time zone"
      variant="outlined"
      color="primary"
      :hint="HINT"
      persistent-hint
      :error-messages="error"
      :disabled="disabled || !!error"
      class="mt-2"
      @update:model-value="pick"
      @focusin="selectText"
    />
    <p v-else class="text-caption text-medium-emphasis">{{ HINT }}</p>
  </div>
</template>
