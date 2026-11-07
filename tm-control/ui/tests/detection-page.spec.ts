// The Detection page: the detector, the model Frigate runs, the models on the device, the two label lists, and for
// admins the Frigate+ key form.
import type { VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../src/api/schema'
import { ADMIN, VIEWER, apiError, json, signedIn } from './fake-api'
import { click, mountApp } from './mount'

type ModelsState = components['schemas']['ModelsState']

const MODELS_PATH = 'GET /api/v1/models'
const SECRETS = 'GET /api/v1/secrets'

// What GET /models answers in fake mode after fake-reset: a Coral unit running the fixture's Frigate+ model
const MODELS: ModelsState = {
  detector: 'edgetpu',
  frigate_answers: true,
  default: 'installer_default',
  running: { name: '0123456789abcdef0123456789abcdef', kind: 'frigate_plus', source: 'frigate' },
  models: [
    {
      name: 'yolov9-s-relu6-tpumax_512_int8_edgetpu.tflite',
      kind: 'installer_default',
      title: 'yolov9-s-relu6-tpumax_512_int8_edgetpu.tflite',
      trained_at: null,
      type: null,
      detectors: [],
      width: null,
      height: null,
      files: [
        {
          name: 'yolov9-s-relu6-tpumax_512_int8_edgetpu.tflite',
          size: 1024,
          sha256: '5f70bf18a086007016e948b04aed3b82103a36bea41755b6cddfaf10ace3c6ef',
        },
      ],
      complete: true,
      running: false,
      usable: null,
      deletable: false,
      problem: null,
    },
    {
      name: '0123456789abcdef0123456789abcdef',
      kind: 'frigate_plus',
      title: 'Test site yolov9',
      trained_at: '2026-10-01T12:00:00Z',
      type: 'yolo-generic',
      detectors: ['edgetpu'],
      width: 320,
      height: 320,
      files: [
        {
          name: '0123456789abcdef0123456789abcdef',
          size: 4096,
          sha256: 'ad7facb2586fc6e966c004d7d1d16b024f5805ff7cb47c7a85dabd8b48892ca7',
        },
        {
          name: '0123456789abcdef0123456789abcdef.json',
          size: 433,
          sha256: '0da6c00a63ab4a05687f4ac37828997208812c11d7150fb68d96e9f245db9a25',
        },
      ],
      complete: true,
      running: true,
      usable: true,
      deletable: false,
      problem: null,
    },
    {
      name: 'mine.tflite',
      kind: 'local',
      title: 'My model',
      trained_at: '2026-10-01T12:00:00Z',
      type: 'yolo-generic',
      detectors: ['edgetpu'],
      width: 320,
      height: 320,
      files: [
        { name: 'mine.tflite', size: 2048, sha256: 'e5a00aa9991ac8a5ee3109844d84a55583bd20572ad3ffcd42792f3c36b183ad' },
        { name: 'mine.tflite.json', size: 417, sha256: '794130b2088706bdfa3b97fe6bc46a3da3e0fe0d8082d09e7e812bef4dae12e0' },
      ],
      complete: true,
      running: false,
      usable: true,
      deletable: true,
      problem: null,
    },
  ],
  labels: {
    recognised: ['person', 'bicycle', 'car'],
    source: 'sidecar',
    tracked: ['bicycle', 'person', 'car', 'bus', 'motorcycle', 'dog'],
  },
}

const TWO_SECRETS = [
  { name: 'thingsboard_access_token', title: 'ThingsBoard access token', set: true, ends_with: '0001', restarts: ['node-red-tm.service'] },
  { name: 'frigate_plus_api_key', title: 'Frigate+ API key', set: false, ends_with: null, restarts: ['frigate.service'] },
]

function headings(wrapper: VueWrapper) {
  return wrapper.findAll('h2').map((h) => h.text().trim())
}

// The text of the list item for the model with this title
function item(wrapper: VueWrapper, title: string) {
  const found = wrapper.findAll('.v-list-item').filter((i) => i.text().includes(title))
  expect(found.length, `one list item for "${title}"`).toBe(1)
  return found[0]
}

describe('the Detection page', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => {
    // jsdom has none of these; the copy and link tests add them
    Reflect.deleteProperty(navigator, 'clipboard')
    Reflect.deleteProperty(window, 'isSecureContext')
    Reflect.deleteProperty(Element.prototype, 'scrollIntoView')
  })

  it('lists the models with the running one marked and the detector named', async () => {
    signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    expect(headings(wrapper)).toEqual(['Object detection', 'What the model recognises', 'Frigate+'])
    expect(wrapper.text()).toContain('This device detects with edgetpu.')
    expect(wrapper.text()).toContain('Frigate runs Test site yolov9, a Frigate+ model.')
    expect(wrapper.text()).not.toContain("Frigate isn't answering")

    const plus = item(wrapper, 'Test site yolov9')
    expect(plus.text()).toContain('running')
    expect(plus.text()).toContain('0123456789abcdef0123456789abcdef') // the file name, which differs from the title
    expect(plus.text()).toContain('trained 2026-10-01, yolo-generic, for edgetpu, 320×320')
    expect(plus.text()).toContain('0123456789abcdef0123456789abcdef, 4.0 KB, SHA-256 ad7facb2586f')
    expect(plus.text()).toContain('0123456789abcdef0123456789abcdef.json, 433 bytes, SHA-256 0da6c00a63ab')
    const hash = plus.find('[title="ad7facb2586fc6e966c004d7d1d16b024f5805ff7cb47c7a85dabd8b48892ca7"]')
    expect(hash.text()).toBe('SHA-256 ad7facb2586f')

    expect(item(wrapper, 'My model').text()).not.toContain('running')
    // The installer's entry has no sidecar: its title is its file name, shown once, and it has no facts line
    const installer = item(wrapper, 'yolov9-s-relu6-tpumax_512_int8_edgetpu.tflite')
    expect(installer.text().split('yolov9-s-relu6-tpumax_512_int8_edgetpu.tflite')).toHaveLength(2)
    expect(installer.text()).not.toContain('trained')
    expect(installer.text()).toContain('1.0 KB, SHA-256 5f70bf18a086')
  })

  it("marks a model that can't run on this detector, and one that is incomplete", async () => {
    const [installer, plus, mine] = MODELS.models
    const models = [
      installer,
      plus,
      { ...mine, detectors: ['hailo8l'], usable: false },
      { ...mine, name: 'half.tflite', title: 'half.tflite', complete: false, usable: null, files: [mine.files[0]],
        problem: 'The sidecar is missing.' },
    ]
    signedIn(VIEWER, { [MODELS_PATH]: { ...MODELS, models } })
    const { wrapper } = await mountApp('/detection')
    expect(item(wrapper, 'My model').text()).toContain("can't run on this detector")
    expect(item(wrapper, 'half.tflite').text()).toContain('incomplete')
    expect(item(wrapper, 'half.tflite').text()).toContain('The sidecar is missing.')
  })

  it('shows a viewer the page without the key form or any action', async () => {
    const api = signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    expect(headings(wrapper)).toContain('Frigate+')
    expect(wrapper.find('#frigate-plus').text()).toContain('Settings, System, Detectors and model')
    expect(wrapper.findAll('form')).toEqual([])
    // The label lists' Copy buttons are the only buttons: nothing that changes the device
    expect(wrapper.findAll('main button').map((b) => b.text().trim())).toEqual(['Copy', 'Copy'])
    expect(api.sent.some((r) => r.path === '/api/v1/secrets')).toBe(false) // viewers get 403 there
  })

  it('shows an admin the Frigate+ key form from GET /secrets', async () => {
    signedIn(ADMIN, { [MODELS_PATH]: MODELS, [SECRETS]: { secrets: TWO_SECRETS } })
    const { wrapper } = await mountApp('/detection')
    const section = wrapper.find('#frigate-plus')
    expect(section.findAll('h3').map((h) => h.text().trim())).toEqual(['Frigate+ API key'])
    expect(section.text()).toContain('Not set.')
    expect(wrapper.text()).not.toContain('ThingsBoard access token')
  })

  it('copies the recognised labels as comma-separated text', async () => {
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
    signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    const recognises = wrapper.findAll('section section').find((s) => s.find('h3').text() === 'Recognises')!
    expect(recognises.text()).toContain('person')
    await recognises.find('button').trigger('click')
    await vi.waitFor(() => expect(recognises.text()).toContain('Copied.'))
    expect(writeText).toHaveBeenCalledWith('person, bicycle, car')
  })

  it('says when Frigate is not answering and the labels are unknown', async () => {
    const offline: ModelsState = {
      ...MODELS,
      frigate_answers: false,
      running: { ...MODELS.running, source: 'config_file' },
      labels: { recognised: null, source: null, tracked: ['person', 'car'] },
    }
    signedIn(VIEWER, { [MODELS_PATH]: offline })
    const { wrapper } = await mountApp('/detection')
    expect(wrapper.text()).toContain("Frigate isn't answering; this is what its config file says.")
    expect(wrapper.text()).toContain(
      "Frigate isn't answering, and the running model has no sidecar on the device.",
    )
    expect(wrapper.text()).toContain('Tracked by this device')
  })

  it('names the installer model and an unknown detector in words', async () => {
    const [installer] = MODELS.models
    const state: ModelsState = {
      ...MODELS,
      detector: null,
      running: { name: installer.name, kind: 'installer_default', source: 'frigate' },
      models: [{ ...installer, running: true }],
    }
    signedIn(VIEWER, { [MODELS_PATH]: state })
    const { wrapper } = await mountApp('/detection')
    expect(wrapper.text()).toContain("Frigate's detector is unknown.")
    expect(wrapper.text()).toContain(`Frigate runs ${installer.title}, the installer's model.`)
  })

  it('offers Try again when the models do not load', async () => {
    let loads = 0
    signedIn(VIEWER, {
      [MODELS_PATH]: () => {
        loads += 1
        return loads === 1 ? apiError(500, 'error', 'The device answered with an error.') : json(200, MODELS)
      },
    })
    const { wrapper } = await mountApp('/detection')
    expect(wrapper.text()).toContain('The device answered with an error.')
    await click(wrapper, 'Try again')
    expect(wrapper.text()).toContain('Frigate runs Test site yolov9, a Frigate+ model.')
  })

  it('is linked from the menu after Device', async () => {
    signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    const menu = wrapper.findAll('.v-navigation-drawer a').map((a) => a.attributes('href'))
    expect(menu.indexOf('/detection')).toBe(menu.indexOf('/device') + 1)
  })

  it('has the Frigate+ section a link can name', async () => {
    signedIn(ADMIN, { [MODELS_PATH]: MODELS, [SECRETS]: { secrets: TWO_SECRETS } })
    const scrolled = vi.fn()
    Element.prototype.scrollIntoView = scrolled
    const { wrapper } = await mountApp('/detection#frigate-plus')
    expect(wrapper.find('#frigate-plus').exists()).toBe(true)
    expect(scrolled).toHaveBeenCalled()
  })
})
