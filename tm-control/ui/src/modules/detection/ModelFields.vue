<!--
  What Frigate needs to know about a model file that came without its .json (POST /models/{name}/sidecar): its type,
  input size, input layout, and labels, and optionally a name for the model list (the file name when left empty). For a Coral or a Hailo-8L the fields start with Frigate's documented example
  for that detector. Emits `saved` with the model's entry once the device has written the sidecar.
-->
<script setup lang="ts">
import { ref } from 'vue'
import { api, messageOf } from '../../api/client'
import type { components } from '../../api/schema'

type ModelOut = components['schemas']['ModelOut']

const props = defineProps<{ name: string; detector: string | null }>()
const emit = defineEmits<{ saved: [model: ModelOut] }>()

// The values Frigate accepts for each (its ModelConfig)
const MODEL_TYPES = ['dfine', 'rfdetr', 'ssd', 'yolox', 'yolonas', 'yolo-generic']
const TENSORS = ['nchw', 'nhwc', 'hwnc', 'hwcn']
const PIXEL_FORMATS = ['rgb', 'bgr', 'yuv']
const DTYPES = [{ title: 'Not set', value: null }, 'float', 'float_denorm', 'int']

const EXAMPLES: Record<string, { type: string; side: string; tensor: string; pixels: string }> = {
  edgetpu: { type: 'yolo-generic', side: '320', tensor: 'nhwc', pixels: 'rgb' },
  hailo8l: { type: 'yolo-generic', side: '640', tensor: 'nhwc', pixels: 'rgb' },
}
const example = props.detector ? EXAMPLES[props.detector] : undefined

const modelType = ref<string | null>(example?.type ?? null)
const width = ref(example?.side ?? '')
const height = ref(example?.side ?? '')
const tensor = ref<string | null>(example?.tensor ?? null)
const pixels = ref<string | null>(example?.pixels ?? null)
const dtype = ref<string | null>(null)
const labels = ref('')
const modelName = ref('')

const required = (value: unknown) => (value !== null && value !== '') || 'Fill this in.'
const side = (value: string) =>
  (/^[0-9]+$/.test(value) && Number(value) >= 1 && Number(value) <= 8192) || 'A whole number from 1 to 8192.'
const someLabels = (value: string) => lines(value).length > 0 || 'One label per line, at least one.'

function lines(text: string) {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
}

const form = ref<{ validate: () => Promise<{ valid: boolean }> } | null>(null)
const saving = ref(false)
const error = ref('')

async function save() {
  if (!(await form.value?.validate())?.valid) return
  saving.value = true
  error.value = ''
  try {
    const { data } = await api.POST('/api/v1/models/{name}/sidecar', {
      params: { path: { name: props.name } },
      body: {
        model_type: modelType.value!,
        width: Number(width.value),
        height: Number(height.value),
        input_tensor: tensor.value!,
        input_pixel_format: pixels.value!,
        input_dtype: dtype.value,
        labels: lines(labels.value),
        name: modelName.value.trim() || null,
      },
    })
    emit('saved', data!)
  } catch (caught) {
    error.value = messageOf(caught)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <v-form ref="form" @submit.prevent="save">
    <p class="text-body-1 mb-4">
      {{ name }} came without its .json, so Frigate doesn't know how to use it yet. Fill in what whoever trained the
      model gives.<template v-if="example"> The fields start with Frigate's example for {{ detector }}.</template>
    </p>
    <v-text-field
      v-model="modelName"
      label="Name"
      hint="Shown in the model list. Left empty, the file name is used."
      persistent-hint
      variant="outlined"
      class="mb-2"
    />
    <v-select v-model="modelType" :items="MODEL_TYPES" label="Model type" variant="outlined" :rules="[required]" />
    <div class="d-flex ga-4">
      <v-text-field v-model="width" label="Width" type="number" variant="outlined" :rules="[side]" />
      <v-text-field v-model="height" label="Height" type="number" variant="outlined" :rules="[side]" />
    </div>
    <v-select v-model="tensor" :items="TENSORS" label="Input tensor" variant="outlined" :rules="[required]" />
    <v-select v-model="pixels" :items="PIXEL_FORMATS" label="Input pixel format" variant="outlined" :rules="[required]" />
    <v-select v-model="dtype" :items="DTYPES" label="Input data type" variant="outlined" />
    <v-textarea
      v-model="labels"
      label="Labels"
      hint="One per line, in the model's order."
      persistent-hint
      variant="outlined"
      rows="6"
      :rules="[someLabels]"
    />
    <v-alert v-if="error" type="error" class="mt-4">{{ error }}</v-alert>
    <v-btn type="submit" color="primary" size="large" class="mt-4" :loading="saving">Save</v-btn>
  </v-form>
</template>
