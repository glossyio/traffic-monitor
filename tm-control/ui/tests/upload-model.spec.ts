// The upload dialog's content: one archive, or a model file with or without its .json, and the fields form for a
// model file that came alone.
import { File as NodeFile } from 'node:buffer'
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'
import type { components } from '../src/api/schema'
import UploadModel from '../src/modules/detection/UploadModel.vue'
import { apiError, fakeApi, json } from './fake-api'
import { click, field, mountAlone } from './mount'

type ModelOut = components['schemas']['ModelOut']

const UPLOAD = '/api/v1/models/upload'

function model(name: string, changes: Partial<ModelOut> = {}): ModelOut {
  return {
    name,
    kind: 'local',
    title: 'My model',
    trained_at: null,
    type: 'yolo-generic',
    detectors: ['edgetpu'],
    width: 320,
    height: 320,
    files: [],
    complete: true,
    running: false,
    usable: true,
    deletable: true,
    problem: null,
    labels: null,
    ...changes,
  }
}

// Node's File, not jsdom's: Node's fetch, which the tests run, can't read jsdom's (a browser's own File it can)
function file(name: string, size: number) {
  return new NodeFile([new Uint8Array(size)], name) as unknown as File
}

// Choose files in the v-file-input, as the browser's picker would
async function choose(wrapper: VueWrapper, files: File[]) {
  const input = wrapper.find<HTMLInputElement>('input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: files, configurable: true })
  await input.trigger('change')
  await flushPromises()
}

describe('uploading a model', () => {
  beforeEach(() => document.body.replaceChildren())

  it('sends an archive as one PUT with an octet-stream body', async () => {
    const api = fakeApi({ [`PUT ${UPLOAD}/mine.zip`]: json(201, model('mine.tflite')) })
    const wrapper = mountAlone(UploadModel, { detector: 'edgetpu' })
    await choose(wrapper, [file('mine.zip', 300)])
    await click(wrapper, 'Upload')
    expect(api.sent).toEqual([{ method: 'PUT', path: `${UPLOAD}/mine.zip`, body: 300 }])
    expect(wrapper.text()).toContain('Uploaded My model.')
    expect(wrapper.emitted('uploaded')).toHaveLength(1)
  })

  it('sends a pair as two PUTs, the sidecar first', async () => {
    const api = fakeApi({
      [`PUT ${UPLOAD}/mine.tflite.json`]: json(201, model('mine.tflite', { complete: false })),
      [`PUT ${UPLOAD}/mine.tflite`]: json(201, model('mine.tflite')),
    })
    const wrapper = mountAlone(UploadModel, { detector: 'edgetpu' })
    await choose(wrapper, [file('mine.tflite', 2048), file('mine.tflite.json', 400)])
    await click(wrapper, 'Upload')
    expect(api.sent.map((r) => [r.path, r.body])).toEqual([
      [`${UPLOAD}/mine.tflite.json`, 400],
      [`${UPLOAD}/mine.tflite`, 2048],
    ])
    expect(wrapper.text()).toContain('Uploaded My model.')
    expect(wrapper.find('form').exists()).toBe(false) // no fields form: the .json came with it
  })

  it('opens the fields form after a bare model file and posts the sidecar', async () => {
    const api = fakeApi({
      [`PUT ${UPLOAD}/bare.tflite`]: json(201, model('bare.tflite', { title: 'bare.tflite', complete: false })),
      'POST /api/v1/models/bare.tflite/sidecar': json(201, model('bare.tflite', { title: 'bare.tflite' })),
    })
    const wrapper = mountAlone(UploadModel, { detector: 'edgetpu' })
    await choose(wrapper, [file('bare.tflite', 1000)])
    await click(wrapper, 'Upload')
    expect(wrapper.find('form').exists()).toBe(true)
    // Frigate's documented example for a Coral is filled in; the labels are the model's own
    expect(field(wrapper, 'Width').element.value).toBe('320')
    await field(wrapper, 'Name').setValue('Placeholder model')
    await field(wrapper, 'Labels').setValue('person\nbicycle\n\ncar\n')
    await click(wrapper, 'Save')
    expect(api.sent.at(-1)).toEqual({
      method: 'POST',
      path: '/api/v1/models/bare.tflite/sidecar',
      body: {
        model_type: 'yolo-generic',
        width: 320,
        height: 320,
        input_tensor: 'nhwc',
        input_pixel_format: 'rgb',
        input_dtype: null,
        labels: ['person', 'bicycle', 'car'],
        name: 'Placeholder model',
      },
    })
    expect(wrapper.text()).toContain('Uploaded bare.tflite.')
    expect(wrapper.find('form').exists()).toBe(false)
  })

  it('sends no name when the Name field is left empty, so the file name is used', async () => {
    const api = fakeApi({
      [`PUT ${UPLOAD}/bare.tflite`]: json(201, model('bare.tflite', { title: 'bare.tflite', complete: false })),
      'POST /api/v1/models/bare.tflite/sidecar': json(201, model('bare.tflite', { title: 'bare.tflite' })),
    })
    const wrapper = mountAlone(UploadModel, { detector: 'edgetpu' })
    await choose(wrapper, [file('bare.tflite', 1000)])
    await click(wrapper, 'Upload')
    await field(wrapper, 'Name').setValue('   ')
    await field(wrapper, 'Labels').setValue('car')
    await click(wrapper, 'Save')
    expect(api.sent.at(-1)?.body).toMatchObject({ labels: ['car'], name: null })
  })

  it('shows the API message when an upload is refused', async () => {
    const refused = 'A model by that name is on the device already.'
    fakeApi({ [`PUT ${UPLOAD}/mine.zip`]: apiError(409, 'conflict', refused) })
    const wrapper = mountAlone(UploadModel, { detector: 'edgetpu' })
    await choose(wrapper, [file('mine.zip', 300)])
    await click(wrapper, 'Upload')
    expect(wrapper.find('.v-alert').text()).toContain(refused)
    expect(wrapper.emitted('uploaded')).toBeUndefined()
  })

  it('sends a .json alone as a sidecar, to finish a model file already on the device', async () => {
    const api = fakeApi({ [`PUT ${UPLOAD}/bare.tflite.json`]: json(201, model('bare.tflite', { title: 'Bare' })) })
    const wrapper = mountAlone(UploadModel, { detector: 'edgetpu' })
    await choose(wrapper, [file('bare.tflite.json', 400)])
    await click(wrapper, 'Upload')
    expect(api.sent).toEqual([{ method: 'PUT', path: `${UPLOAD}/bare.tflite.json`, body: 400 }])
    expect(wrapper.text()).toContain('Uploaded Bare.')
    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.emitted('uploaded')).toHaveLength(1)
  })

  it('says how to finish a pair whose model file was refused after its .json', async () => {
    const refused = 'The file is larger than 100 MB.'
    const api = fakeApi({
      [`PUT ${UPLOAD}/mine.tflite.json`]: json(201, model('mine.tflite', { complete: false })),
      [`PUT ${UPLOAD}/mine.tflite`]: apiError(413, 'too_large', refused),
    })
    const wrapper = mountAlone(UploadModel, { detector: 'edgetpu' })
    await choose(wrapper, [file('mine.tflite', 2048), file('mine.tflite.json', 400)])
    await click(wrapper, 'Upload')
    expect(api.sent).toHaveLength(2)
    expect(wrapper.find('.v-alert').text()).toBe(
      `${refused} Its .json is on the device: upload the model file on its own to finish it.`,
    )
    expect(wrapper.emitted('uploaded')).toHaveLength(1) // the .json reached the device
  })

  it('sends nothing for two .json files, and says what to choose', async () => {
    const api = fakeApi({})
    const wrapper = mountAlone(UploadModel, { detector: 'edgetpu' })
    await choose(wrapper, [file('a.json', 10), file('b.json', 10)])
    await click(wrapper, 'Upload')
    expect(api.sent).toEqual([])
    expect(wrapper.text()).toContain('Choose one package, or one model file with or without its .json.')
    expect(wrapper.text()).not.toContain('b.json.json')
  })

  it('makes its buttons at least 44 px tall', () => {
    fakeApi({})
    const wrapper = mountAlone(UploadModel, { detector: 'edgetpu' })
    const buttons = wrapper.findAll('.v-card-actions button')
    expect(buttons.map((b) => b.text().trim())).toEqual(['Close', 'Upload'])
    for (const button of buttons) expect(button.attributes('style')).toContain('min-height: 44px')
  })

  it('lets any file be picked: a Frigate+ model file has no extension', () => {
    fakeApi({})
    const wrapper = mountAlone(UploadModel, { detector: 'edgetpu' })
    expect(wrapper.find('input[type="file"]').attributes('accept')).toBeUndefined()
  })

  it('sends nothing for two models at once, and says what to choose', async () => {
    const api = fakeApi({})
    const wrapper = mountAlone(UploadModel, { detector: 'edgetpu' })
    await choose(wrapper, [file('a.tflite', 10), file('b.tflite', 10)])
    await click(wrapper, 'Upload')
    expect(api.sent).toEqual([])
    expect(wrapper.text()).toContain('Choose one package, or one model file with or without its .json.')
  })
})
