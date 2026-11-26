<!--
  The Mounting page (/location/mounting), for admins only: how the unit is mounted at the place in use, one section per
  sensor (GET /surveys/{id}/mounting). After each change it waits, then sends the whole form as a dry run
  (PUT /surveys/{id}/mounting) and shows what the API worked out: the one of tilt and distance that wasn't measured,
  what changed, and whether "Did the unit move or turn?" must be answered. Save sends the same form for real. The page
  works out no mounting value itself; the README's "The Mounting page" has the layout and the reasons.
-->
<script setup lang="ts">
import { mdiArrowLeft } from '@mdi/js'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError, api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'
import HeadingDial from './HeadingDial.vue'
import { both, decimal, savedUnit, saveUnit, shown, typed, type Unit } from './lengths'
import MountSideView from './MountSideView.vue'

type PlacesState = components['schemas']['PlacesState']
type SurveyOut = components['schemas']['SurveyOut']
type MountingState = components['schemas']['MountingState']
type SensorMounting = components['schemas']['SensorMounting']
type SensorMountingIn = components['schemas']['SensorMountingIn']
type MountingIn = components['schemas']['MountingIn']
type MountingOut = components['schemas']['MountingOut']
type PreviousMounting = components['schemas']['PreviousMounting']
type Measured = 'pitch' | 'distance'

// How long the page waits after a change before it asks the API, in ms
const PAUSE = 400

const NOT_A_NUMBER = 'Enter a number, such as 12 or 12.5.'
const OWN = ':own' // "My own measurements"; no mount's key can start with a colon
const STAYED = 'No, it is where it was. I measured it better.'
const MOVED = 'Yes, it was moved or turned.'

const KINDS: Record<string, string> = { cameras: 'Camera', radars: 'Radar', airquality_monitors: 'Air-quality monitor' }

const FIELD_WORDS: Record<string, string> = {
  heading_deg: 'heading',
  pitch_deg: 'tilt',
  height_m: 'height',
  view_distance_m: 'distance',
  mount: 'usual mount',
}

// A number field: the value the API gets (metres or degrees), the text shown, and whether the text can't be read. The
// value changes only when someone types a number, so a value nobody touched is sent exactly as it was loaded, and text
// typed back to what the page last put in the field (`put`) gives that value back: a length saved as 3.00 m reads
// 9.8 ft, which typed would be 2.99 m.
interface NumberField {
  value: number | null
  text: string
  bad: boolean
  put: { text: string; value: number | null }
}

interface Section {
  sensor_type: string
  sensor_name: string
  camera: string | null // a radar's camera, which "Same as" follows
  previous: PreviousMounting | null
  same: boolean
  heading: number | null
  height: NumberField
  pitch: NumberField
  distance: NumberField
  measured: Measured
  mount: string | null
}

const router = useRouter()

const unit = ref<Unit>(savedUnit())
const place = ref<SurveyOut | null>(null)
const state = ref<MountingState | null>(null) // as loaded
const sections = ref<Section[]>([])
const loadError = ref('')
const noPlace = ref(false)

// A camera or a radar has the height and the tilt; anything else (an air-quality monitor) has the heading only
function mounted(section: { sensor_type: string }) {
  return section.sensor_type === 'cameras' || section.sensor_type === 'radars'
}

function key(sensor: { sensor_type: string; sensor_name: string }) {
  return `${sensor.sensor_type}/${sensor.sensor_name}`
}

function length(value: number | null): NumberField {
  const text = shown(value, unit.value)
  return { value, text, bad: false, put: { text, value } }
}

function degrees(value: number | null): NumberField {
  const text = value === null ? '' : String(value)
  return { value, text, bad: false, put: { text, value } }
}

// The one of tilt and distance that isn't measured holds nothing of its own: the field shows the API's value
function sectionOf(sensor: SensorMounting): Section {
  const measured = sensor.measured ?? 'pitch'
  return {
    sensor_type: sensor.sensor_type,
    sensor_name: sensor.sensor_name,
    camera: sensor.camera,
    previous: sensor.previous,
    same: sensor.same_as_camera,
    heading: sensor.heading_deg ?? null,
    height: length(sensor.height_m ?? null),
    pitch: degrees(measured === 'pitch' ? (sensor.pitch_deg ?? null) : null),
    distance: length(measured === 'distance' ? (sensor.view_distance_m ?? null) : null),
    measured,
    mount: sensor.mount ?? null,
  }
}

// What the API gets for a section: a following radar by name only, a monitor its heading, the rest all of it. The one
// of tilt and distance that isn't measured is sent empty: the API works it out.
function sent(section: Section): SensorMountingIn {
  const named = { sensor_type: section.sensor_type, sensor_name: section.sensor_name }
  if (section.same) return { ...named, same_as_camera: true }
  if (!mounted(section)) return { ...named, heading_deg: section.heading, same_as_camera: false }
  return {
    ...named,
    heading_deg: section.heading,
    height_m: section.height.value,
    pitch_deg: section.measured === 'pitch' ? section.pitch.value : null,
    view_distance_m: section.measured === 'distance' ? section.distance.value : null,
    measured: section.measured,
    mount: section.mount,
    same_as_camera: false,
  }
}

const body = computed(() => sections.value.map(sent))
const bodyText = computed(() => JSON.stringify(body.value))
// Unreadable text holds the form back only in a field that is sent: the height and the measured one
function sentFields(section: Section): NumberField[] {
  if (section.same || !mounted(section)) return []
  return [section.height, section.measured === 'pitch' ? section.pitch : section.distance]
}

const anyBad = computed(() => sections.value.some((section) => sentFields(section).some((field) => field.bad)))

// The form as loaded, and the form the newest answer is for
const loadedText = ref('')
const answeredText = ref('')
const answer = ref<MountingOut | null>(null)
const pending = ref(false)
const refusal = ref<{ index: number; field: string; message: string } | null>(null)
const formError = ref('')
// The newest dry run got no answer, or an error the same form may not get again: Try again sends it
const retry = ref(false)

// The values a section shows where the page doesn't hold them: the worked-out one of tilt and distance, and the side
// view. The newest answer's, else as loaded.
function shownValues(section: Section): SensorMounting | undefined {
  const sensors = answer.value?.sensors ?? state.value?.sensors ?? []
  return sensors.find((sensor) => key(sensor) === key(section))
}

function loadedValues(sensor: { sensor_type: string; sensor_name: string }): SensorMounting | undefined {
  return state.value?.sensors.find((each) => key(each) === key(sensor))
}

function workedOut(section: Section, field: 'pitch' | 'distance'): number | null {
  const values = shownValues(section)
  return (field === 'pitch' ? values?.pitch_deg : values?.view_distance_m) ?? null
}

function fieldText(section: Section, field: 'pitch' | 'distance'): string {
  if (section.measured === field) return section[field].text
  const value = workedOut(section, field)
  return field === 'pitch' ? (value === null ? '' : String(value)) : shown(value, unit.value)
}

// The unit changes only how the lengths read
watch(unit, (chosen) => {
  saveUnit(chosen)
  for (const section of sections.value) {
    for (const field of [section.height, section.distance]) {
      if (!field.bad) field.text = shown(field.value, chosen)
      field.put = { text: shown(field.value, chosen), value: field.value }
    }
  }
})

// A number as typed: empty clears the value; text that isn't a number keeps the value and says so
function typeLength(field: NumberField, text: string) {
  field.text = text
  if (text.trim() === '') Object.assign(field, { value: null, bad: false })
  else if (text.trim() === field.put.text) Object.assign(field, { value: field.put.value, bad: false })
  else {
    const metres = typed(text, unit.value)
    if (metres === null) field.bad = true
    else Object.assign(field, { value: metres, bad: false })
  }
}

function typeDegrees(field: NumberField, text: string) {
  field.text = text
  const value = decimal(text)
  if (text.trim() === '') Object.assign(field, { value: null, bad: false })
  else if (value !== null) Object.assign(field, { value, bad: false })
  else field.bad = true
}

// The other of tilt and distance is now measured. It starts from the value the API works out for the form as typed (a
// dry run that is waiting or on its way is let finish first, and one that got no answer is sent again), or, when the
// API works none out, from the value it held when it was last measured, so switching changes no number.
async function measuredChanged(section: Section, measured: Measured) {
  while (pending.value) await checked()
  if (retry.value && !anyBad.value) await dryRun()
  if (measured === 'distance') {
    section.distance = length(workedOut(section, 'distance') ?? section.distance.value)
    section.pitch = degrees(section.pitch.value) // no longer sent, so text it couldn't read is forgotten
  } else {
    section.pitch = degrees(workedOut(section, 'pitch') ?? section.pitch.value)
    section.distance = length(section.distance.value)
  }
  section.measured = measured
}

// The usual mounts, and "My own measurements"
const mountChoice = ref<string | null>(null)

function choosable() {
  return sections.value.filter((section) => mounted(section) && !section.same)
}

function startingMount(): string | null {
  const kept = choosable()
  const keys = new Set(kept.map((section) => section.mount))
  if (keys.size === 1 && !keys.has(null)) return [...keys][0]
  const anyValue = kept.some((section) =>
    [section.height, section.pitch, section.distance].some((field) => field.value !== null),
  )
  return keys.size === 1 && anyValue ? OWN : null
}

function pickMount(choice: string | null) {
  mountChoice.value = choice
  const mount = state.value?.mounts.find((each) => each.key === choice)
  for (const section of choosable()) {
    if (choice === OWN) section.mount = null
    else if (mount) {
      section.height = length(mount.height_m)
      section.pitch = degrees(mount.pitch_deg)
      section.distance = length(null) // a distance from before the mount isn't this mount's
      section.measured = 'pitch'
      section.mount = mount.key
    }
  }
}

function mountTitle(mountKey: string) {
  return state.value?.mounts.find((mount) => mount.key === mountKey)?.title ?? mountKey
}

// "Same as <camera>": unticked, the radar starts from its camera's values as the form has them. Either way the usual
// mounts' group shows what the sections that are left now share.
function cameraOf(section: Section): Section | undefined {
  return sections.value.find((each) => each.sensor_type === 'cameras' && each.sensor_name === section.camera)
}

function setSame(section: Section, same: boolean | null) {
  section.same = same === true
  const camera = cameraOf(section)
  if (!section.same && camera) {
    const copy = (field: NumberField, make: (value: number | null) => NumberField) =>
      field.bad ? { ...field } : make(field.value)
    Object.assign(section, {
      heading: camera.heading,
      height: copy(camera.height, length),
      pitch: copy(camera.pitch, degrees),
      distance: copy(camera.distance, length),
      measured: camera.measured,
      mount: camera.mount,
    })
  }
  mountChoice.value = startingMount()
}

// Last time's values at this place, offered after a move here
function previousWords(previous: PreviousMounting) {
  const parts: string[] = []
  if (previous.height_m !== null) parts.push(`${shown(previous.height_m, unit.value)} ${unit.value} up`)
  if (previous.pitch_deg !== null) parts.push(`tilted ${previous.pitch_deg}°`)
  else if (previous.view_distance_m !== null) {
    parts.push(`${shown(previous.view_distance_m, unit.value)} ${unit.value} to the centre of the view`)
  }
  if (previous.mount !== null) {
    const title = mountTitle(previous.mount)
    parts.push(title.charAt(0).toLowerCase() + title.slice(1))
  }
  return `From last time: ${parts.join(', ')}`
}

// A radar that follows its camera offers its own last values only when they aren't its camera's: the camera's are
// offered in the camera's section, and one save confirms both
function offersPrevious(section: Section): boolean {
  if (!section.previous || !mounted(section)) return false
  const camera = section.same ? cameraOf(section) : undefined
  return !camera?.previous || JSON.stringify(camera.previous) !== JSON.stringify(section.previous)
}

// Fills the section with last time's values; a following radar is unticked first, so it keeps its camera's heading
function usePrevious(section: Section) {
  const previous = section.previous
  if (!previous) return
  if (section.same) setSame(section, false)
  const measured = previous.measured ?? 'pitch'
  Object.assign(section, {
    height: length(previous.height_m),
    pitch: degrees(measured === 'pitch' ? previous.pitch_deg : null),
    distance: length(measured === 'distance' ? previous.view_distance_m : null),
    measured,
    mount: previous.mount,
  })
  mountChoice.value = startingMount()
}

// The API's sentence for a refused value, under its field
function refusedHere(index: number, field: string): string[] {
  const refused = refusal.value
  return refused && refused.index === index && refused.field === field ? [refused.message] : []
}

const FIELDS_SHOWN = ['heading_deg', 'height_m', 'pitch_deg', 'view_distance_m']

function hasField(index: number, field: string): boolean {
  const section = sections.value[index]
  return !!section && !section.same && (mounted(section) ? FIELDS_SHOWN : ['heading_deg']).includes(field)
}

function refusedInSection(index: number): string {
  const refused = refusal.value
  if (!refused || refused.index !== index) return ''
  return hasField(index, refused.field) ? '' : refused.message
}

// The dry run: after each change the page waits, then sends the whole form. A counter drops an answer that isn't the
// newest request's.
let timer: ReturnType<typeof setTimeout> | undefined
let waiting = false
let running: Promise<void> = Promise.resolve()
let requests = 0
onBeforeUnmount(() => clearTimeout(timer))

watch([bodyText, anyBad], ([text], [before]) => {
  clearTimeout(timer)
  waiting = false
  requests += 1
  if (text !== before) refusal.value = null
  if (text !== before && text !== loadedText.value) result.value = null // the form no longer is what was saved
  if (anyBad.value || text === answeredText.value) {
    pending.value = false
    return
  }
  pending.value = true
  waiting = true
  timer = setTimeout(() => void dryRun(), PAUSE)
})

// The dry run that is waiting is sent now; then the one on its way is answered
async function checked() {
  if (waiting) void dryRun()
  await running
}

// The question's answer: the API's suggestion until the person picks one, and again once the changes that count are
// not the ones the person answered for (another turn, say)
const choice = ref<'moved' | 'measured' | null>(null)
let chosenByPerson = false
let answeredFor = ''

function countingKey(found: MountingOut | null): string {
  return JSON.stringify(
    (found?.changes ?? [])
      .filter((change) => change.counts)
      .map((change) => {
        const after = found?.sensors.find((sensor) => key(sensor) === key(change))
        return [key(change), change.field, after?.[change.field as keyof SensorMounting] ?? null]
      }),
  )
}

function chooseAnswer(value: 'moved' | 'measured' | null) {
  choice.value = value
  chosenByPerson = true
  answeredFor = countingKey(answer.value)
}

function dryRun(): Promise<void> {
  running = ask()
  return running
}

async function ask() {
  if (!place.value) return
  clearTimeout(timer)
  waiting = false
  const request = (requests += 1)
  const text = bodyText.value
  pending.value = true
  formError.value = ''
  retry.value = false
  try {
    const { data } = await api.PUT('/api/v1/surveys/{survey_id}/mounting', {
      params: { path: { survey_id: place.value.id } },
      body: { sensors: body.value, dry_run: true },
    })
    if (request !== requests) return
    const found = data as MountingOut
    answer.value = found
    answeredText.value = text
    if (!found.ask) {
      choice.value = null
      chosenByPerson = false
    } else if (!chosenByPerson || countingKey(found) !== answeredFor) {
      chosenByPerson = false
      choice.value = found.suggested
    }
  } catch (error) {
    if (request !== requests) return
    retry.value = !(error instanceof ApiError && (error.status === 422 || error.status === 409))
    await refused(error)
  } finally {
    if (request === requests) pending.value = false
  }
}

// A refusal: under its field, or above Save; a 409 loads the page again
async function refused(error: unknown) {
  const detail = error instanceof ApiError ? (error.detail as { field?: string; index?: number } | null) : null
  if (error instanceof ApiError && error.status === 422 && typeof detail?.index === 'number' && detail.field) {
    refusal.value = { index: detail.index, field: detail.field, message: error.message }
    return
  }
  formError.value = messageOf(error)
  if (error instanceof ApiError && error.status === 409 && error.code !== 'answer_needed') await load()
}

const dirty = computed(() => bodyText.value !== loadedText.value)
const canSave = computed(
  () =>
    state.value !== null &&
    state.value.nodered &&
    dirty.value &&
    !anyBad.value &&
    !pending.value &&
    !saving.value &&
    refusal.value === null &&
    answeredText.value === bodyText.value,
)

// What changed, as the question lists it: the value as loaded, then as the dry run has it
function valueWords(field: string, value: unknown): string {
  if (value === null || value === undefined) return 'not set'
  if (field === 'heading_deg' || field === 'pitch_deg') return `${value}°`
  if (field === 'height_m' || field === 'view_distance_m') return both(value as number, unit.value)
  if (field === 'mount') return mountTitle(String(value))
  return String(value)
}

const changeLines = computed(() =>
  (answer.value?.changes ?? []).filter((change) => change.counts).map((change) => {
    const before = loadedValues(change)?.[change.field as keyof SensorMounting]
    const after = answer.value?.sensors.find((sensor) => key(sensor) === key(change))?.[
      change.field as keyof SensorMounting
    ]
    const what = FIELD_WORDS[change.field] ?? change.field
    return `${change.sensor_name}: ${what} ${valueWords(change.field, before)} to ${valueWords(change.field, after)}`
  }),
)

const list = new Intl.ListFormat('en', { style: 'long', type: 'conjunction' })

function names(sensors: { sensor_name: string }[]) {
  return list.format([...new Set(sensors.map((sensor) => sensor.sensor_name))])
}

const startsNewFor = computed(() => names((answer.value?.changes ?? []).filter((change) => change.counts)))

// Saving: the same form with dry_run false, and the answer to the question when it is shown
const saving = ref(false)
const result = ref<{ text: string; error: boolean } | null>(null)

function savedWords(saved: MountingOut) {
  if (saved.reloaded === false) {
    return "Saved. Node-RED hasn't loaded the settings yet; the new deployment appears once it does. Don't save again."
  }
  if (saved.new_deployments.length) return `Saved. A new deployment started for ${names(saved.new_deployments)}.`
  return 'Saved.'
}

async function save() {
  if (!place.value) return
  saving.value = true
  result.value = null
  formError.value = ''
  const sending: MountingIn = { sensors: body.value, dry_run: false }
  if (answer.value?.ask) sending.moved = choice.value === 'moved'
  try {
    const { data } = await api.PUT('/api/v1/surveys/{survey_id}/mounting', {
      params: { path: { survey_id: place.value.id } },
      body: sending,
    })
    result.value = { text: savedWords(data as MountingOut), error: false }
    await load()
  } catch (error) {
    result.value = { text: messageOf(error), error: true }
    if (error instanceof ApiError && error.code === 'answer_needed') {
      void dryRun() // the save needs the answer, so the question comes up
    } else if (error instanceof ApiError && error.status === 422) {
      // once: under its field when the page shows that field, else beside Save
      const detail = error.detail as { field?: string; index?: number } | null
      if (typeof detail?.index === 'number' && detail.field && hasField(detail.index, detail.field)) {
        refusal.value = { index: detail.index, field: detail.field, message: error.message }
        result.value = null
      }
    } else if (error instanceof ApiError && error.status === 409) {
      await load()
    }
  } finally {
    saving.value = false
  }
}

// The place in use, then its mounting. A save's result stays.
async function load() {
  loadError.value = ''
  noPlace.value = false
  try {
    const { data } = await api.GET('/api/v1/surveys')
    const places = data as PlacesState
    place.value = places.surveys.find((survey) => survey.id === places.in_use) ?? null
    if (!place.value) {
      state.value = null
      noPlace.value = true
      return
    }
    const mounting = await api.GET('/api/v1/surveys/{survey_id}/mounting', {
      params: { path: { survey_id: place.value.id } },
    })
    state.value = mounting.data as MountingState
    sections.value = state.value.sensors.map(sectionOf)
    answer.value = null
    loadedText.value = bodyText.value
    answeredText.value = bodyText.value
    refusal.value = null
    choice.value = null
    chosenByPerson = false
    mountChoice.value = startingMount()
  } catch (error) {
    state.value = null
    loadError.value = messageOf(error)
  }
}

function cancel() {
  void router.push('/location')
}

onMounted(load)
</script>

<template>
  <div>
    <v-btn variant="text" color="primary" to="/location" :prepend-icon="mdiArrowLeft" class="mb-2 ms-n4">
      Location
    </v-btn>
    <h1 class="text-h5 text-primary mb-2">Mounting</h1>
    <template v-if="place">
      <p class="text-subtitle-1 font-weight-medium text-break">{{ place.description ?? 'No description' }}</p>
      <p class="text-body-2 text-secondary mb-4">{{ place.id }}</p>
    </template>
    <p class="text-body-1 mb-6">
      How the unit is mounted at this place. The numbers are stored with each deployment and help place the recorded
      paths on a street plan.
    </p>

    <v-alert v-if="noPlace" type="warning">
      No place is in use. Deploy a place on the Location page first.
    </v-alert>
    <v-alert v-else-if="loadError" type="warning">
      {{ loadError }}
      <template #append>
        <v-btn variant="text" @click="load">Try again</v-btn>
      </template>
    </v-alert>
    <v-progress-linear v-else-if="!state" indeterminate color="primary" />

    <template v-if="state">
      <v-alert v-if="!state.nodered" type="warning" class="mb-6">
        Node-RED didn't answer, so changes can't be saved now.
      </v-alert>

      <v-radio-group v-model="unit" label="Units" inline hide-details :disabled="saving" class="mb-4">
        <v-radio value="ft" label="Feet" />
        <v-radio value="m" label="Metres" />
      </v-radio-group>

      <v-radio-group
        :model-value="mountChoice"
        label="Start from a usual mount"
        hide-details
        :disabled="saving"
        class="mb-2"
        @update:model-value="pickMount"
      >
        <v-radio v-for="mount in state.mounts" :key="mount.key" :value="mount.key" :label="mount.title" />
        <v-radio :value="OWN" label="My own measurements" />
      </v-radio-group>

      <section
        v-for="(section, index) in sections"
        :key="key(section)"
        :data-sensor="section.sensor_name"
        class="border-t pt-6 mt-6"
      >
        <h2 class="text-h6 text-break">{{ section.sensor_name }}</h2>
        <p class="text-body-2 text-secondary mb-4">{{ KINDS[section.sensor_type] ?? section.sensor_type }}</p>

        <v-checkbox
          v-if="section.camera"
          :model-value="section.same"
          :label="`Same as ${section.camera}`"
          hide-details
          :disabled="saving"
          class="mb-2"
          @update:model-value="(same) => setSame(section, same)"
        />
        <v-alert v-if="section.previous && offersPrevious(section)" type="info" variant="tonal" class="mb-6">
          <p class="text-body-1 mb-3">{{ previousWords(section.previous) }}</p>
          <v-btn variant="outlined" color="primary" min-height="44" :disabled="saving" @click="usePrevious(section)">
            Use these values
          </v-btn>
        </v-alert>

        <p v-if="section.same" class="text-body-1">Takes {{ section.camera }}'s heading, height, and tilt.</p>

        <template v-else>
          <HeadingDial v-model:heading="section.heading" label="Which way it faces" :disabled="saving" />
          <p v-for="message in refusedHere(index, 'heading_deg')" :key="message" class="text-body-2 text-error mt-2">
            {{ message }}
          </p>

          <template v-if="mounted(section)">
            <div class="mt-6">
              <v-text-field
                :model-value="section.height.text"
                label="Height above the road"
                inputmode="decimal"
                autocomplete="off"
                :suffix="unit"
                max-width="20rem"
                :hint="both(section.height.value, unit)"
                persistent-hint
                hide-details="auto"
                :error-messages="section.height.bad ? [NOT_A_NUMBER] : refusedHere(index, 'height_m')"
                :disabled="saving"
                @update:model-value="(text: string) => typeLength(section.height, text)"
              />
              <p class="text-body-2 text-secondary mt-1">
                From the road surface straight below the camera up to the lens. Use a tape measure.
              </p>
            </div>

            <v-radio-group
              :model-value="section.measured"
              hide-details
              class="mt-4"
              :disabled="saving"
              @update:model-value="(measured) => measuredChanged(section, measured as Measured)"
            >
              <v-radio value="pitch" label="I measured the tilt" />
              <v-radio value="distance" label="I measured the distance" />
            </v-radio-group>

            <div class="mt-4">
              <v-text-field
                :model-value="fieldText(section, 'pitch')"
                label="Tilt below level"
                inputmode="decimal"
                autocomplete="off"
                suffix="°"
                max-width="20rem"
                :error-messages="
                  section.measured === 'pitch' && section.pitch.bad ? [NOT_A_NUMBER] : refusedHere(index, 'pitch_deg')
                "
                hide-details="auto"
                :disabled="saving || section.measured !== 'pitch'"
                @update:model-value="(text: string) => typeDegrees(section.pitch, text)"
              />
              <p class="text-body-2 text-secondary mt-1">
                How far the camera points down. 0 is level, 90 is straight down. Hold a phone's level app against the
                camera.
              </p>
            </div>

            <div class="mt-4">
              <v-text-field
                :model-value="fieldText(section, 'distance')"
                label="Distance to the centre of the view"
                inputmode="decimal"
                autocomplete="off"
                :suffix="unit"
                max-width="20rem"
                :hint="
                  both(section.measured === 'distance' ? section.distance.value : workedOut(section, 'distance'), unit)
                "
                persistent-hint
                hide-details="auto"
                :error-messages="
                  section.measured === 'distance' && section.distance.bad
                    ? [NOT_A_NUMBER]
                    : refusedHere(index, 'view_distance_m')
                "
                :disabled="saving || section.measured !== 'distance'"
                @update:model-value="(text: string) => typeLength(section.distance, text)"
              />
              <p class="text-body-2 text-secondary mt-1">
                Along the ground, from the spot right below the camera to the spot on the road at the very centre of
                the picture.
              </p>
            </div>

            <div class="mt-6">
              <MountSideView
                :height-m="shownValues(section)?.height_m ?? null"
                :pitch-deg="shownValues(section)?.pitch_deg ?? null"
                :distance-m="shownValues(section)?.view_distance_m ?? null"
                :unit="unit"
              />
            </div>
          </template>
        </template>

        <v-alert v-if="refusedInSection(index)" type="error" class="mt-4">{{ refusedInSection(index) }}</v-alert>
      </section>

      <section v-if="answer?.ask" class="border-t pt-6 mt-6" aria-labelledby="mounting-question">
        <h2 id="mounting-question" class="text-h6 mb-2">Did the unit move or turn?</h2>
        <div class="mb-2">
          <p v-for="line in changeLines" :key="line" class="text-body-1 text-break">{{ line }}</p>
        </div>
        <v-radio-group
          :model-value="choice"
          hide-details
          :disabled="saving"
          @update:model-value="(value) => chooseAnswer(value as 'moved' | 'measured' | null)"
        >
          <v-radio value="measured" :label="STAYED" />
          <v-radio value="moved" :label="MOVED" />
        </v-radio-group>
        <p v-if="choice === 'measured'" class="text-body-1 mt-2">The record of the running deployment is corrected.</p>
        <p v-else-if="choice === 'moved'" class="text-body-1 mt-2">
          A new deployment starts now for {{ startsNewFor }}. Traffic already recorded keeps the old values.
        </p>
      </section>

      <div class="d-flex flex-wrap align-center ga-3 border-t pt-6 mt-6">
        <v-btn color="primary" size="large" :loading="saving" :disabled="!canSave" @click="save">Save</v-btn>
        <v-btn variant="text" color="primary" size="large" :disabled="saving" @click="cancel">Cancel</v-btn>
        <p v-if="result && !result.error" role="status" class="text-body-1">{{ result.text }}</p>
      </div>
      <v-alert v-if="result?.error" type="error" class="mt-4">{{ result.text }}</v-alert>
      <v-alert v-if="formError" type="error" class="mt-4">
        {{ formError }}
        <template v-if="retry && !anyBad" #append>
          <v-btn variant="text" @click="dryRun">Try again</v-btn>
        </template>
      </v-alert>
    </template>
  </div>
</template>
