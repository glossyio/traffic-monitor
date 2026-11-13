// The Detection page: the detector, the model Frigate runs, the models on the device, the two label lists, and for
// admins the Frigate+ key form.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../src/api/schema'
import { ADMIN, VIEWER, apiError, json, signedIn } from './fake-api'
import { click, clickInDialog, dialogButtons, dialogText, mountAlone, mountApp } from './mount'
import LabelChips from '../src/modules/detection/LabelChips.vue'
import ModelBlock, { type Block } from '../src/modules/detection/ModelBlock.vue'

type ModelsState = components['schemas']['ModelsState']
type ModelOut = components['schemas']['ModelOut']

const MODELS_PATH = 'GET /api/v1/models'
const SECRETS = 'GET /api/v1/secrets'

// What GET /models answers in fake mode after fake-reset: a Coral unit running the fixture's Frigate+ model
const MODELS: ModelsState = {
  detector: 'edgetpu',
  frigate_answers: true,
  frigate_safe_mode: false,
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
      labels: null,
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
      labels: ['person', 'bicycle', 'car'],
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
      labels: ['person', 'bicycle', 'car'],
    },
  ],
  labels: {
    recognised: ['person', 'bicycle', 'car'],
    source: 'sidecar',
    tracked: ['bicycle', 'person', 'car', 'bus', 'motorcycle', 'dog'],
  },
  fetch: null,
}

const TWO_SECRETS = [
  { name: 'thingsboard_access_token', title: 'ThingsBoard access token', set: true, ends_with: '0001', restarts: ['node-red-tm.service'] },
  { name: 'frigate_plus_api_key', title: 'Frigate+ API key', set: false, ends_with: null, restarts: ['frigate.service'] },
]

function headings(wrapper: VueWrapper) {
  return wrapper.findAll('h2').map((h) => h.text().trim())
}

// The block for the model with this title
function item(wrapper: VueWrapper, title: string) {
  const found = wrapper.findAll('.model').filter((i) => i.text().includes(title))
  expect(found.length, `one model block for "${title}"`).toBe(1)
  return found[0]
}

// The page's buttons other than the panels' titles
function actions(wrapper: VueWrapper) {
  return wrapper
    .findAll('main button')
    .filter((b) => !b.classes('v-expansion-panel-title'))
    .map((b) => b.text().trim())
}

// A card's action buttons: the ones outside its fold
function cardActions(card: ReturnType<typeof item>) {
  return card
    .findAll('button')
    .filter((b) => !b.element.closest('.fold'))
    .map((b) => b.text().trim())
}

// The title (a button) of the panel whose title starts with `title`
function panel(wrapper: VueWrapper, title: string) {
  const found = wrapper.findAll('.v-expansion-panel-title').filter((t) => t.text().trim().startsWith(title))
  expect(found.length, `one panel titled "${title}…"`).toBe(1)
  return found[0]
}

// The in-use card's fold, and in it the list whose h4 starts with `title`
function usedFold(wrapper: VueWrapper) {
  return section(wrapper, 'Model in use').find('.model .fold')
}
function list(wrapper: VueWrapper, title: string) {
  const found = usedFold(wrapper)
    .findAll('section')
    .filter((s) => s.find('h4').exists() && s.find('h4').text().startsWith(title))
  expect(found.length, `one list titled "${title}…"`).toBe(1)
  return found[0]
}

// The section whose h2 starts with `title`
function section(wrapper: VueWrapper, title: string) {
  const found = wrapper.findAll('section').filter((s) => s.find('h2').exists() && s.find('h2').text().startsWith(title))
  expect(found.length, `one section titled "${title}…"`).toBe(1)
  return found[0]
}

// The value under `label` in the facts grid
function fact(wrapper: VueWrapper, label: string) {
  const found = wrapper.findAll('.facts > div').filter((c) => c.element.children[0]?.textContent?.trim() === label)
  expect(found.length, `one fact labelled "${label}"`).toBe(1)
  return found[0].element.children[1].textContent?.trim()
}

// GET /models with `name` running instead of the Frigate+ model
function running(name: string, kind: ModelOut['kind']): ModelsState {
  return {
    ...MODELS,
    running: { name, kind, source: 'frigate' },
    models: MODELS.models.map((model) => ({ ...model, running: model.name === name })),
  }
}

describe('the Detection page', () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => {
    // jsdom has none of these; the copy and link tests add them
    Reflect.deleteProperty(navigator, 'clipboard')
    Reflect.deleteProperty(window, 'isSecureContext')
    Reflect.deleteProperty(Element.prototype, 'scrollIntoView')
  })

  it('shows the four sections, with every model a card', async () => {
    signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    expect(headings(wrapper)).toEqual([
      'Object detection',
      'Model in use',
      'Frigate+',
      'Other models on this device (2)',
    ])
    expect(wrapper.text()).toContain(
      'See which model Frigate detects objects with and what it recognises. Administrators can switch models and ' +
        'set the Frigate+ API key.',
    )
    expect(fact(wrapper, 'Detector')).toBe('edgetpu')
    expect(fact(wrapper, 'Running model')).toBe('Test site yolov9, a Frigate+ model')
    expect(wrapper.text()).not.toContain("Frigate isn't answering")

    const plus = section(wrapper, 'Model in use').find('.model.in-use')
    expect(plus.text()).toContain('Test site yolov9')
    expect(plus.text()).toContain('In use')
    expect(plus.text()).toContain('0123456789abcdef0123456789abcdef') // the file name, which differs from the title
    expect(plus.text()).toContain('Frigate+ model, trained 2026-10-01, yolo-generic, for edgetpu, 320×320')
    expect(plus.text()).toContain('0123456789abcdef0123456789abcdef, 4.0 KB, SHA-256 ad7facb2586f')
    expect(plus.text()).toContain('0123456789abcdef0123456789abcdef.json, 433 bytes, SHA-256 0da6c00a63ab')
    const hash = plus.find('[title="ad7facb2586fc6e966c004d7d1d16b024f5805ff7cb47c7a85dabd8b48892ca7"]')
    expect(hash.text()).toBe('SHA-256 ad7facb2586f')
    expect(wrapper.findAll('.model.in-use')).toHaveLength(1)

    // No outer panel: the other models' cards are on the page, each with its own closed fold
    const others = section(wrapper, 'Other models').findAll('.model')
    expect(others.map((m) => m.find('h3').text())).toEqual(["The installer's model", 'My model'])
    for (const card of [plus, ...others]) {
      expect(card.element.parentElement?.closest('.v-expansion-panel')).toBeNull()
      expect(card.find('.fold .v-expansion-panel-title').attributes('aria-expanded')).toBe('false')
    }
    expect(item(wrapper, 'My model').text()).not.toContain('In use')
    expect(item(wrapper, 'My model').text()).toContain('Local model, trained 2026-10-01')
    // The installer's block has no sidecar: its file name is its facts line, shown once
    const installer = item(wrapper, "The installer's model")
    expect(installer.text().split('yolov9-s-relu6-tpumax_512_int8_edgetpu.tflite')).toHaveLength(2)
    expect(installer.text()).not.toContain('trained')
    expect(installer.text()).toContain('1.0 KB, SHA-256 5f70bf18a086')
    expect(wrapper.findAll('h3').map((h) => h.text().trim())).toEqual([
      'Test site yolov9',
      "The installer's model",
      'My model',
    ])
  })

  it('shows the two lists inside the card in use, and nowhere above it', async () => {
    // MODELS: the Frigate+ model runs; Frigate reports its list
    const frigate = { ...MODELS, labels: { ...MODELS.labels, source: 'frigate' as const } }
    signedIn(VIEWER, { [MODELS_PATH]: frigate })
    const { wrapper } = await mountApp('/detection')
    expect(section(wrapper, 'Object detection').findAll('.v-expansion-panel').length).toBe(0)
    expect(section(wrapper, 'Object detection').text()).not.toContain('Frigate tracks only')
    const card = section(wrapper, 'Model in use').find('.model')
    const fold = card.find('.fold')
    expect(fold.find('.v-expansion-panel-title').text()).toBe('Files and objects')
    expect(fold.findAll('h4').map((h) => h.text())).toEqual([
      `Objects the running model recognises (${MODELS.labels.recognised!.length})`,
      expect.stringMatching(/^Objects tracked on this device \(6/),
    ])
    expect(fold.findAll('.v-expansion-panel').length).toBe(1) // the lists are not panels of their own
    expect(fold.text()).toContain('Frigate tracks only the objects that are in both lists.')
    expect(fold.text()).toContain('As Frigate reports them.')
    expect(fold.text()).not.toContain('Objects it recognises')
    expect(fold.find('.v-expansion-panel-title').attributes('aria-expanded')).toBe('false')
  })

  it('keeps the tracked-but-not-recognised chips on the card, outside the fold and above the buttons', async () => {
    signedIn(ADMIN, { [MODELS_PATH]: MODELS, [SECRETS]: { secrets: TWO_SECRETS } })
    const { wrapper } = await mountApp('/detection')
    const card = section(wrapper, 'Model in use').find('.model')
    const chips = card.find('.not-recognised')
    expect(chips.text()).toContain('Tracked but not recognised by the running model:')
    expect(chips.findAll('.v-chip.text-warning').map((c) => c.text())).toEqual(['bus', 'motorcycle', 'dog'])
    expect(chips.element.closest('.fold')).toBeNull()
    expect(card.findAll('.not-recognised')).toHaveLength(1)
    // between the facts and the buttons
    const order = [...card.element.querySelectorAll('.text-secondary, .not-recognised, .d-flex.mt-2, .fold')]
    const at = (el: Element | undefined) => order.indexOf(el!)
    const buttons = card.findAll('button').find((b) => b.text().trim() === 'Download')!.element.parentElement
    expect(at(card.find('.text-secondary').element)).toBeLessThan(at(chips.element))
    expect(at(chips.element)).toBeLessThan(at(buttons ?? undefined))
    expect(at(buttons ?? undefined)).toBeLessThan(at(card.find('.fold').element))
  })

  it('gives a default with no file on the device a fold with the lists and no file lines', async () => {
    const cpu: ModelsState = {
      ...MODELS,
      detector: 'cpu',
      default: 'frigate_default',
      running: { name: null, kind: 'frigate_default', source: 'frigate' },
      models: [{ ...MODELS.models[2], running: false }],
    }
    signedIn(VIEWER, { [MODELS_PATH]: cpu })
    const { wrapper } = await mountApp('/detection')
    const fold = usedFold(wrapper)
    expect(fold.find('.v-expansion-panel-title').text()).toBe('Objects')
    expect(fold.findAll('h4').map((h) => h.text())).toEqual([
      'Objects the running model recognises (3)',
      'Objects tracked on this device (6, 3 not recognised)',
    ])
    expect(fold.text()).not.toContain('SHA-256')
    expect(fold.text()).not.toContain('KB')
  })

  it('makes a card for a running model that has no entry in the list', async () => {
    const named = 'abc0123456789abcdef0123456789abc'
    const state: ModelsState = {
      ...MODELS,
      running: { name: named, kind: 'local', source: 'config_file' },
      models: MODELS.models.map((model) => ({ ...model, running: false })),
    }
    signedIn(ADMIN, { [MODELS_PATH]: state, [SECRETS]: { secrets: TWO_SECRETS } })
    const { wrapper } = await mountApp('/detection')
    const cards = section(wrapper, 'Model in use').findAll('.model')
    expect(cards).toHaveLength(1)
    expect(cards[0].find('h3').text()).toBe(named)
    expect(cards[0].text()).toContain("Named in Frigate's config; its files aren't on this device.")
    expect(cards[0].text()).toContain('In use')
    expect(cardActions(cards[0] as ReturnType<typeof item>)).toEqual([])
    expect(cards[0].findAll('.fold h4')).toHaveLength(2)
    expect(section(wrapper, 'Other models').findAll('.model')).toHaveLength(3)
  })

  it('makes an "Unknown model" card when the running model cannot be read', async () => {
    const state: ModelsState = {
      ...MODELS,
      running: { name: null, kind: null, source: null },
      models: MODELS.models.map((model) => ({ ...model, running: false })),
      labels: { recognised: null, source: null, tracked: [] },
    }
    signedIn(VIEWER, { [MODELS_PATH]: state })
    const { wrapper } = await mountApp('/detection')
    const card = section(wrapper, 'Model in use').find('.model')
    expect(card.find('h3').text()).toBe('Unknown model')
    expect(card.text()).toContain("Frigate's model couldn't be read.")
    expect(list(wrapper, 'Objects tracked on this device').text()).toContain('None.')
    expect(list(wrapper, 'Objects the running model recognises').text()).not.toContain('(')
  })

  it("leaves the other models' own lists as they were", async () => {
    signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    const mine = item(wrapper, 'My model')
    expect(mine.find('.fold h4').text()).toBe('Objects it recognises (3)')
    expect(mine.text()).toContain("Doesn't recognise 3 objects tracked on this device:")
    expect(mine.find('.fold .v-expansion-panel-title').text()).toBe('Files and objects')
    expect(mine.text()).not.toContain('Frigate tracks only')
  })

  it('opens each fold on its own, so the card in use and another card can be open at once', async () => {
    signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    const toggles = [
      item(wrapper, 'My model').find('.fold .v-expansion-panel-title'),
      item(wrapper, 'Test site yolov9').find('.fold .v-expansion-panel-title'),
    ]
    for (const toggle of toggles) await toggle.trigger('click')
    expect(toggles.map((toggle) => toggle.attributes('aria-expanded'))).toEqual(['true', 'true'])
  })

  it("lists every model under the others, and makes an Unknown model card, when Frigate's model is unknown", async () => {
    const unknown: ModelsState = {
      ...MODELS,
      running: { name: null, kind: null, source: null },
      models: MODELS.models.map((model) => ({ ...model, running: false })),
    }
    signedIn(VIEWER, { [MODELS_PATH]: unknown })
    const { wrapper } = await mountApp('/detection')
    expect(section(wrapper, 'Model in use').find('.model.in-use h3').text()).toBe('Unknown model')
    expect(fact(wrapper, 'Running model')).toBe('Unknown')
    expect(headings(wrapper)).toEqual([
      'Object detection',
      'Model in use',
      'Frigate+',
      'Other models on this device (3)',
    ])
  })

  it("makes a block for Frigate's built-in model, with a fold of the lists only, when the device has no file for it", async () => {
    const cpu: ModelsState = {
      ...MODELS,
      detector: 'cpu',
      default: 'frigate_default',
      running: { name: null, kind: 'frigate_default', source: 'frigate' },
      models: [{ ...MODELS.models[2], running: false }],
    }
    signedIn(VIEWER, { [MODELS_PATH]: cpu })
    const { wrapper } = await mountApp('/detection')
    const builtIn = section(wrapper, 'Model in use').find('.model.in-use')
    expect(builtIn.text()).toContain("Frigate's built-in model")
    expect(builtIn.text()).toContain('Built into Frigate.')
    expect(builtIn.find('.fold .v-expansion-panel-title').text()).toBe('Objects')
    expect(fact(wrapper, 'Running model')).toBe("Frigate's built-in model")
    expect(headings(wrapper)).toContain('Other models on this device (1)')
  })

  it('says so when there are no other models', async () => {
    const alone: ModelsState = { ...MODELS, default: null, models: [MODELS.models[1]] }
    signedIn(VIEWER, { [MODELS_PATH]: alone })
    const { wrapper } = await mountApp('/detection')
    expect(headings(wrapper)).toContain('Other models on this device (0)')
    expect(section(wrapper, 'Other models').text()).toContain('No other models on this device.')
    expect(section(wrapper, 'Other models').find('.model').exists()).toBe(false)
  })

  it('leaves the "no other models" line out when there are some', async () => {
    signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    expect(wrapper.text()).not.toContain('No other models on this device.')
  })

  it.each([
    ['frigate', 'As Frigate reports them.'],
    ['sidecar', "From the model's .json, because Frigate didn't say."],
    ['labels_file', "From the installer's labels file, because Frigate didn't say."],
  ] as const)('says where the running model\'s list came from: %s', async (source, caption) => {
    signedIn(VIEWER, { [MODELS_PATH]: { ...MODELS, labels: { ...MODELS.labels, source } } })
    const { wrapper } = await mountApp('/detection')
    expect(list(wrapper, 'Objects the running model recognises').text()).toContain(caption)
  })

  it('fills the recognised objects the device tracks, with the legend', async () => {
    const labels = { recognised: ['person', 'cat'], source: 'frigate', tracked: ['person'] } as const
    signedIn(VIEWER, { [MODELS_PATH]: { ...MODELS, labels } })
    const { wrapper } = await mountApp('/detection')
    const recognises = list(wrapper, 'Objects the running model recognises (2)')
    const chip = (text: string) => recognises.findAll('.v-chip').find((c) => c.text() === text)!
    expect(chip('person').classes()).toContain('v-chip--variant-tonal')
    expect(chip('cat').classes()).toContain('v-chip--variant-outlined')
    expect(recognises.text()).toContain('Filled: tracked on this device.')
  })

  it('flags tracked objects the running model does not recognise, in the list and while the fold is closed', async () => {
    signedIn(VIEWER, { [MODELS_PATH]: MODELS }) // tracks bus, motorcycle, and dog, which it doesn't recognise
    const { wrapper } = await mountApp('/detection')
    const tracked = list(wrapper, 'Objects tracked on this device (6, 3 not recognised)')
    expect(tracked.findAll('.v-chip.text-warning').map((c) => c.text())).toEqual(['bus', 'motorcycle', 'dog'])
    expect(tracked.text()).toContain("Amber: the running model doesn't recognise it.")

    expect(usedFold(wrapper).find('.v-expansion-panel-title').attributes('aria-expanded')).toBe('false')
    const mismatch = wrapper.find('.not-recognised')
    expect(mismatch.text()).toContain('Tracked but not recognised by the running model:')
    expect(mismatch.findAll('.v-chip.text-warning').map((c) => c.text())).toEqual(['bus', 'motorcycle', 'dog'])
    expect(mismatch.element.closest('.v-expansion-panel')).toBeNull()
  })

  it('flags nothing when every tracked object is recognised', async () => {
    const labels = { recognised: ['person', 'car'], source: 'frigate', tracked: ['person'] } as const
    signedIn(VIEWER, { [MODELS_PATH]: { ...MODELS, labels } })
    const { wrapper } = await mountApp('/detection')
    expect(list(wrapper, 'Objects tracked on this device').find('h4').text()).toBe('Objects tracked on this device (1)')
    expect(wrapper.find('.not-recognised').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Amber:')
  })

  it("flags nothing when the running model's labels aren't known", async () => {
    const labels = { recognised: null, source: null, tracked: ['person'] }
    signedIn(VIEWER, { [MODELS_PATH]: { ...MODELS, labels } })
    const { wrapper } = await mountApp('/detection')
    expect(list(wrapper, 'Objects tracked on this device').find('h4').text()).toBe('Objects tracked on this device (1)')
    expect(wrapper.find('.not-recognised').exists()).toBe(false)
  })

  it('names what a switch to another model would lose, but not on the model in use', async () => {
    signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    const mine = item(wrapper, 'My model')
    expect(mine.text()).toContain("Doesn't recognise 3 objects tracked on this device:")
    expect(mine.findAll('.v-chip.text-warning').map((c) => c.text())).toEqual(['bus', 'motorcycle', 'dog'])
    expect(item(wrapper, 'Test site yolov9').text()).not.toContain("Doesn't recognise")
    expect(item(wrapper, "The installer's model").text()).not.toContain("Doesn't recognise") // its labels aren't known
  })

  const DIFFERENT = "Frigate reports a different list than this model's .json."
  it.each([
    ['Frigate and the .json differ', ['person', 'dog'], 'frigate', true],
    ['the same objects in another order', ['car', 'person', 'bicycle'], 'frigate', false],
    ['a list that is not from Frigate', ['person', 'dog'], 'sidecar', false],
  ] as [string, string[], 'frigate' | 'sidecar', boolean][])(
    'compares the two lists as sets: %s',
    async (_name, recognised, source, shown) => {
      signedIn(VIEWER, { [MODELS_PATH]: { ...MODELS, labels: { ...MODELS.labels, recognised, source } } })
      const { wrapper } = await mountApp('/detection')
      expect(section(wrapper, 'Model in use').find('.fold').text().includes(DIFFERENT)).toBe(shown)
      expect(section(wrapper, 'Object detection').text()).not.toContain(DIFFERENT)
    },
  )

  it('has nothing to compare when the model in use has no labels of its own', async () => {
    const state = running(MODELS.models[0].name, 'installer_default')
    const labels = { ...MODELS.labels, recognised: ['person', 'dog'], source: 'frigate' as const }
    signedIn(VIEWER, { [MODELS_PATH]: { ...state, labels } })
    const { wrapper } = await mountApp('/detection')
    expect(wrapper.text()).not.toContain(DIFFERENT)
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
    const plus = wrapper.find('#frigate-plus').text()
    expect(plus).toContain(
      'When the device is online and has a Frigate+ API key, pick a Frigate+ model in Frigate, under Settings, System, ' +
        'Detectors and model, and Frigate downloads it.',
    )
    expect(plus).toContain(
      "When it's offline, an administrator can upload the model's two files on this page, as a package from whoever " +
        "trained the model or copied from another device's Frigate.",
    )
    expect(wrapper.find('#frigate-plus .v-expansion-panel').exists()).toBe(false) // no key panel for a viewer
    expect(wrapper.findAll('form')).toEqual([])
    // The label lists' Copy buttons are the only buttons: nothing that changes the device
    expect([...new Set(actions(wrapper))]).toEqual(['Copy'])
    expect(api.sent.some((r) => r.path === '/api/v1/secrets')).toBe(false) // viewers get 403 there
  })

  it('shows an admin the Frigate+ key form from GET /secrets', async () => {
    signedIn(ADMIN, { [MODELS_PATH]: MODELS, [SECRETS]: { secrets: TWO_SECRETS } })
    const { wrapper } = await mountApp('/detection')
    const toggle = panel(wrapper, 'API key')
    expect(toggle.text()).toBe('API key not set')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('#frigate-plus form').exists()).toBe(true)
    expect(wrapper.find('#frigate-plus h3').text()).toBe('API key not set') // the panel's title sits inside a heading
    expect(wrapper.findAll('#frigate-plus h3')).toHaveLength(1) // the form's own title is hidden: this one says it
    expect(toggle.element.closest('h3')).not.toBeNull()
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    expect(wrapper.text()).not.toContain('ThingsBoard access token')
  })

  it('says the key is in use only while Frigate runs a Frigate+ model', async () => {
    const set = TWO_SECRETS.map((secret) =>
      secret.name === 'frigate_plus_api_key' ? { ...secret, set: true, ends_with: 'ab12' } : secret,
    )
    signedIn(ADMIN, { [MODELS_PATH]: MODELS, [SECRETS]: { secrets: set } })
    const plus = await mountApp('/detection')
    expect(panel(plus.wrapper, 'API key').text()).toBe('API key set, ending in ab12, in use')

    signedIn(ADMIN, { [MODELS_PATH]: running('mine.tflite', 'local'), [SECRETS]: { secrets: set } })
    const local = await mountApp('/detection')
    expect(panel(local.wrapper, 'API key').text()).toBe('API key set, ending in ab12')

    const bare = TWO_SECRETS.map((secret) =>
      secret.name === 'frigate_plus_api_key' ? { ...secret, set: true, ends_with: null } : secret,
    )
    signedIn(ADMIN, { [MODELS_PATH]: running('mine.tflite', 'local'), [SECRETS]: { secrets: bare } })
    const short = await mountApp('/detection')
    expect(panel(short.wrapper, 'API key').text()).toBe('API key set')
  })

  it('orders the sections: detection, model in use, Frigate+, other models', async () => {
    signedIn(ADMIN, { [MODELS_PATH]: MODELS, [SECRETS]: { secrets: TWO_SECRETS } })
    const { wrapper } = await mountApp('/detection')
    expect(headings(wrapper)).toEqual([
      'Object detection',
      'Model in use',
      'Frigate+',
      expect.stringMatching(/^Other models on this device/),
    ])
  })

  it('puts the Frigate+ heading outside the panel and the key state in the panel title', async () => {
    const set = TWO_SECRETS.map((secret) =>
      secret.name === 'frigate_plus_api_key' ? { ...secret, set: true, ends_with: '0001' } : secret,
    )
    signedIn(ADMIN, { [MODELS_PATH]: MODELS, [SECRETS]: { secrets: set } })
    const { wrapper } = await mountApp('/detection')
    const plus = wrapper.find('#frigate-plus')
    expect(plus.find('h2').text()).toBe('Frigate+')
    expect(plus.find('h2').element.closest('.v-expansion-panel')).toBeNull()
    expect(panel(wrapper, 'API key').text()).toBe('API key set, ending in 0001, in use') // key set, Frigate+ model runs
  })

  it('shows a viewer the Frigate+ text and no panel', async () => {
    signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    const plus = wrapper.find('#frigate-plus')
    expect(plus.findAll('p')).toHaveLength(2)
    expect(plus.findAll('.v-expansion-panel')).toHaveLength(0)
  })

  it('keeps the Frigate+ section when the models cannot load', async () => {
    signedIn(ADMIN, {
      [MODELS_PATH]: apiError(500, 'error', 'The device answered with an error.'),
      [SECRETS]: { secrets: TWO_SECRETS },
    })
    const { wrapper } = await mountApp('/detection')
    expect(wrapper.text()).toContain('The device answered with an error.')
    expect(wrapper.find('#frigate-plus h2').text()).toBe('Frigate+')
    expect(wrapper.find('#frigate-plus form').exists()).toBe(true)
    expect(panel(wrapper, 'API key').text()).toBe('API key not set') // no model is known to run, so no "in use"
  })

  it('copies the recognised labels as comma-separated text', async () => {
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
    signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    await usedFold(wrapper).find('.v-expansion-panel-title').trigger('click')
    const recognises = list(wrapper, 'Objects the running model recognises (3)')
    expect(recognises.text()).toContain('person')
    await recognises.findAll('button').find((b) => b.text().trim() === 'Copy')!.trigger('click')
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
    const warning = "Frigate isn't answering; this is what its config file says."
    expect(wrapper.text()).toContain(warning)
    expect(wrapper.text().indexOf(warning)).toBeLessThan(wrapper.text().indexOf('Detector'))
    expect(wrapper.find('.model.in-use').text()).toContain('Test site yolov9') // what the config file names
    const title = 'Objects the running model recognises'
    expect(list(wrapper, title).find('h4').text().trim()).toBe(title)
    expect(list(wrapper, title).text()).toContain(
      "Frigate isn't answering, and the running model has no sidecar on the device.",
    )
    expect(list(wrapper, 'Objects tracked on this device (2)').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('Tracked by this device')
  })

  it('says when Frigate started in safe mode, and shows what the config file says', async () => {
    const safe: ModelsState = {
      ...MODELS,
      frigate_safe_mode: true,
      running: { ...MODELS.running, source: 'config_file' },
    }
    signedIn(VIEWER, { [MODELS_PATH]: safe })
    const { wrapper } = await mountApp('/detection')
    const warning =
      "Frigate couldn't use its config and started in safe mode, so nothing is detected; this is what the config file says. Use a model to give Frigate a config it can run."
    expect(wrapper.text()).toContain(warning)
    expect(wrapper.text().indexOf(warning)).toBeLessThan(wrapper.text().indexOf('Detector'))
    expect(wrapper.text()).not.toContain("Frigate isn't answering")
    expect(fact(wrapper, 'Detector')).toBe('edgetpu')
    expect(wrapper.find('.model.in-use').text()).toContain('Test site yolov9') // what the config file names
    expect(usedFold(wrapper).findAll('h4').map((h) => h.text())).toEqual([
      `Objects the running model recognises (${MODELS.labels.recognised!.length})`,
      expect.stringMatching(/^Objects tracked on this device \(6/),
    ])
  })

  it("says the running model's labels aren't known when Frigate answers without them", async () => {
    const unknown: ModelsState = { ...MODELS, labels: { recognised: null, source: null, tracked: ['person', 'car'] } }
    signedIn(VIEWER, { [MODELS_PATH]: unknown })
    const { wrapper } = await mountApp('/detection')
    expect(wrapper.text()).toContain("The running model's labels aren't known.")
    const title = 'Objects the running model recognises'
    expect(list(wrapper, title).find('h4').text().trim()).toBe(title)
    expect(wrapper.text()).not.toContain("Frigate isn't answering")
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
    expect(fact(wrapper, 'Detector')).toBe('Unknown')
    expect(fact(wrapper, 'Running model')).toBe("The installer's model")
    expect(wrapper.find('.model.in-use').text()).toContain("The installer's model")
  })

  it('never names a model it does not know', async () => {
    const models = MODELS.models.map((model) => ({ ...model, running: false })) // as the API has it with no name
    signedIn(VIEWER, { [MODELS_PATH]: { ...MODELS, running: { name: null, kind: null, source: null }, models } })
    const { wrapper } = await mountApp('/detection')
    expect(fact(wrapper, 'Running model')).toBe('Unknown')
    expect(wrapper.find('.model.in-use h3').text()).toBe('Unknown model')

    const unnamed = { ...MODELS, running: { name: null, kind: 'frigate_plus', source: 'frigate' } as const }
    signedIn(VIEWER, { [MODELS_PATH]: { ...unnamed, models: [MODELS.models[0]] } })
    const again = await mountApp('/detection')
    expect(fact(again.wrapper, 'Running model')).toBe('A Frigate+ model')
    expect(again.wrapper.find('.model.in-use h3').text()).toBe('Unknown model')
    expect(again.wrapper.text()).not.toContain('null')
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
    expect(fact(wrapper, 'Running model')).toBe('Test site yolov9, a Frigate+ model')
  })

  it('is linked from the menu after Network', async () => {
    signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    const menu = wrapper.findAll('.v-navigation-drawer a').map((a) => a.attributes('href'))
    expect(menu.indexOf('/detection')).toBe(menu.indexOf('/network') + 1)
  })

  it("opens the key panel when a link names it, as the Status page's Set the key does", async () => {
    signedIn(ADMIN, { [MODELS_PATH]: MODELS, [SECRETS]: { secrets: TWO_SECRETS } })
    const scrolled = vi.fn()
    Element.prototype.scrollIntoView = scrolled
    const { wrapper } = await mountApp('/detection#frigate-plus')
    expect(panel(wrapper, 'API key').attributes('aria-expanded')).toBe('true')
    expect(scrolled).toHaveBeenCalled()
    expect(usedFold(wrapper).find('.v-expansion-panel-title').attributes('aria-expanded')).toBe('false')
  })

  it('scrolls a viewer to the Frigate+ text without asking for the secrets', async () => {
    const api = signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const scrolled = vi.fn()
    Element.prototype.scrollIntoView = scrolled
    const { wrapper } = await mountApp('/detection#frigate-plus')
    expect(scrolled).toHaveBeenCalled()
    expect(wrapper.find('#frigate-plus .v-expansion-panel').exists()).toBe(false)
    expect(wrapper.find('#frigate-plus').text()).toContain('When the device is online and has a Frigate+ API key')
    expect(wrapper.findAll('form')).toEqual([])
    expect(api.sent.some((r) => r.path === '/api/v1/secrets')).toBe(false)
  })
})

describe("the Detection page's actions", () => {
  beforeEach(() => document.body.replaceChildren())
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  const MINE = MODELS.models[2]
  const USE_MINE = 'POST /api/v1/models/mine.tflite/use'
  const QUEUED = json(202, { name: 'mine.tflite', applied: 'frigate', restarts: ['frigate.service'] })

  // GET /models answers `before` for the first `count` calls (the page's load included), then `after`
  function changesAfter(count: number, before: ModelsState, after: ModelsState) {
    let calls = 0
    return () => {
      calls += 1
      return json(200, calls <= count ? before : after)
    }
  }

  async function clickIn(scope: ReturnType<typeof item>, text: string) {
    const buttons = scope.findAll('button').filter((b) => b.text().trim() === text)
    expect(buttons.length, `one button reading "${text}"`).toBe(1)
    await buttons[0].trigger('click')
    await flushPromises()
  }

  function modelCalls(api: ReturnType<typeof signedIn>) {
    return api.sent.filter((r) => r.method === 'GET' && r.path === '/api/v1/models').length
  }

  it('uses a model after the confirm and polls until it runs', async () => {
    vi.useFakeTimers()
    const api = signedIn(ADMIN, {
      [SECRETS]: { secrets: TWO_SECRETS },
      [MODELS_PATH]: changesAfter(3, MODELS, running('mine.tflite', 'local')),
      [USE_MINE]: QUEUED,
    })
    const { wrapper } = await mountApp('/detection')
    expect(cardActions(item(wrapper, 'Test site yolov9'))).not.toContain('Use')
    await clickIn(item(wrapper, 'My model'), 'Use')
    expect(dialogText()).toContain('Use My model?')
    expect(dialogText()).toContain("Frigate restarts, which takes about a minute. Traffic isn't counted while it does.")
    await clickInDialog('Use')
    expect(api.sent.filter((r) => r.method === 'POST').map((r) => r.path)).toEqual(['/api/v1/models/mine.tflite/use'])
    expect(wrapper.text()).toContain('Frigate is restarting.')

    await vi.advanceTimersByTimeAsync(3000)
    await vi.advanceTimersByTimeAsync(3000)
    expect(wrapper.text()).toContain('Frigate is restarting.')
    await vi.advanceTimersByTimeAsync(3000) // the third poll sees it running
    expect(wrapper.text()).toContain('Frigate runs My model.')
    expect(wrapper.text()).not.toContain('Frigate is restarting.')
    const moved = section(wrapper, 'Model in use').find('.model.in-use') // moved there, with its result
    expect(moved.text()).toContain('My model')
    expect(moved.text()).toContain('Frigate runs My model.')
    expect(headings(wrapper)).toContain('Other models on this device (2)')
    const calls = modelCalls(api)
    expect(calls).toBe(4)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(modelCalls(api)).toBe(calls) // polling stopped
  })

  it('says when Frigate has not come back after ninety seconds', async () => {
    vi.useFakeTimers()
    signedIn(ADMIN, { [SECRETS]: { secrets: TWO_SECRETS }, [MODELS_PATH]: MODELS, [USE_MINE]: QUEUED })
    const { wrapper } = await mountApp('/detection')
    await clickIn(item(wrapper, 'My model'), 'Use')
    await clickInDialog('Use')
    await vi.advanceTimersByTimeAsync(87_000)
    expect(wrapper.text()).toContain('Frigate is restarting.')
    await vi.advanceTimersByTimeAsync(3000)
    expect(wrapper.text()).toContain("Frigate hasn't come back yet; see the Status page.")
    expect(wrapper.find('main .v-alert a[href="/status"]').text()).toBe('Status page')
  })

  it("shows Frigate's refusal when a use is refused", async () => {
    const refused = 'Frigate refused the config: Model does not support detector type of edgetpu'
    signedIn(ADMIN, {
      [SECRETS]: { secrets: TWO_SECRETS },
      [MODELS_PATH]: MODELS,
      [USE_MINE]: apiError(422, 'frigate_refused', refused),
    })
    const { wrapper } = await mountApp('/detection')
    await clickIn(item(wrapper, 'My model'), 'Use')
    await clickInDialog('Use')
    expect(item(wrapper, 'My model').find('.v-alert').text()).toContain(refused)
    expect(wrapper.text()).not.toContain('Frigate is restarting.')
  })

  it('downloads a package as a blob named <name>.zip', async () => {
    const zip = new Uint8Array([0x50, 0x4b, 0x03, 0x04, 0, 0, 0, 0])
    const api = signedIn(ADMIN, {
      [SECRETS]: { secrets: TWO_SECRETS },
      [MODELS_PATH]: MODELS,
      'GET /api/v1/models/mine.tflite/package': new Response(zip, {
        status: 200,
        headers: { 'Content-Type': 'application/zip', 'Content-Disposition': 'attachment; filename="mine.tflite.zip"' },
      }),
    })
    const blobs: Blob[] = []
    vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
      blobs.push(blob as Blob)
      return 'blob:http://localhost/package'
    })
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const saved: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      saved.push(this.download)
    })
    const { wrapper } = await mountApp('/detection')
    // The installer's model has no sidecar to package: its Download is of the file alone, and it has no Delete
    expect(cardActions(item(wrapper, "The installer's model"))).toEqual(['Use', 'Download'])
    await clickIn(item(wrapper, 'My model'), 'Download')
    expect(api.sent.at(-1)?.path).toBe('/api/v1/models/mine.tflite/package')
    expect(saved).toEqual(['mine.tflite.zip'])
    expect(blobs[0].size).toBe(zip.length)
  })

  // A model file on the device with no .json: uploaded on its own, its details never filled in
  const BARE: ModelOut = {
    name: 'bare.tflite',
    kind: 'local',
    title: 'bare.tflite',
    trained_at: null,
    type: null,
    detectors: [],
    width: null,
    height: null,
    files: [{ name: 'bare.tflite', size: 3, sha256: '039058c6f2c0cb492c533b0a4d14ef77cc0f78abccced5287d84a1a2011cfb81' }],
    complete: false,
    running: false,
    usable: null,
    deletable: true,
    problem: null,
    labels: null,
  }
  const WITH_BARE = { ...MODELS, models: [...MODELS.models, BARE] }
  const INSTALLER_NAME = MODELS.models[0].name

  // The names the page saved files under
  function savedFiles() {
    vi.spyOn(URL, 'createObjectURL').mockImplementation(() => 'blob:http://localhost/file')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const saved: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      saved.push(this.download)
    })
    return saved
  }
  const fileResponse = () =>
    new Response(new Uint8Array([1, 2, 3]), { status: 200, headers: { 'Content-Type': 'application/octet-stream' } })
  const gets = (api: ReturnType<typeof signedIn>) =>
    api.sent.filter((r) => r.method === 'GET' && r.path.startsWith('/api/v1/models/')).map((r) => r.path)

  it('says a model with no .json downloads as its file alone, then saves the file under its own name', async () => {
    const api = signedIn(ADMIN, {
      [SECRETS]: { secrets: TWO_SECRETS },
      [MODELS_PATH]: WITH_BARE,
      'GET /api/v1/models/bare.tflite/file': fileResponse,
    })
    const saved = savedFiles()
    const { wrapper } = await mountApp('/detection')
    expect(cardActions(item(wrapper, 'bare.tflite'))).toEqual(['Use', 'Download', 'Delete'])
    await clickIn(item(wrapper, 'bare.tflite'), 'Download')
    expect(dialogText()).toContain('Download bare.tflite?')
    expect(dialogText()).toContain(
      'It has no .json the device can read, so the download is the model file alone. ' +
        'Whoever uploads the file fills in what Frigate needs to know about it.',
    )
    expect(gets(api)).toEqual([]) // nothing is fetched until the operator has read that
    await clickInDialog('Download')
    expect(gets(api)).toEqual(['/api/v1/models/bare.tflite/file'])
    expect(saved).toEqual(['bare.tflite'])
  })

  it("downloads the file alone when the model's .json is on the device but can't be read", async () => {
    const broken: ModelOut = {
      ...BARE,
      name: 'broken.tflite',
      title: 'broken.tflite',
      files: [
        { name: 'broken.tflite', size: 2, sha256: BARE.files[0].sha256 },
        { name: 'broken.tflite.json', size: 8, sha256: BARE.files[0].sha256 },
      ],
      problem: "The sidecar isn't a JSON object.",
    }
    const api = signedIn(ADMIN, {
      [SECRETS]: { secrets: TWO_SECRETS },
      [MODELS_PATH]: { ...MODELS, models: [...MODELS.models, broken] },
      'GET /api/v1/models/broken.tflite/file': fileResponse,
    })
    const saved = savedFiles()
    const { wrapper } = await mountApp('/detection')
    await clickIn(item(wrapper, 'broken.tflite'), 'Download')
    expect(dialogText()).toContain('It has no .json the device can read')
    await clickInDialog('Download')
    expect(gets(api)).toEqual(['/api/v1/models/broken.tflite/file'])
    expect(saved).toEqual(['broken.tflite'])
  })

  it('downloads nothing when the operator cancels', async () => {
    const api = signedIn(ADMIN, { [SECRETS]: { secrets: TWO_SECRETS }, [MODELS_PATH]: WITH_BARE })
    const saved = savedFiles()
    const { wrapper } = await mountApp('/detection')
    await clickIn(item(wrapper, 'bare.tflite'), 'Download')
    await clickInDialog('Cancel')
    expect(gets(api)).toEqual([])
    expect(saved).toEqual([])
  })

  it("says the installer's model file must be renamed before it's uploaded", async () => {
    const api = signedIn(ADMIN, {
      [SECRETS]: { secrets: TWO_SECRETS },
      [MODELS_PATH]: MODELS,
      [`GET /api/v1/models/${INSTALLER_NAME}/file`]: fileResponse,
    })
    const saved = savedFiles()
    const { wrapper } = await mountApp('/detection')
    await clickIn(item(wrapper, "The installer's model"), 'Download')
    expect(dialogText()).toContain("Download the installer's model?")
    expect(dialogText()).toContain(
      'It has no .json, so the download is the model file alone. A device keeps this file name for its own copy, ' +
        'so rename the file before uploading it. Whoever uploads it fills in what Frigate needs to know about it.',
    )
    await clickInDialog('Download')
    expect(gets(api)).toEqual([`/api/v1/models/${INSTALLER_NAME}/file`])
    expect(saved).toEqual([INSTALLER_NAME])
  })

  it("shows a refused download on the card it was asked from, a default's included", async () => {
    signedIn(ADMIN, {
      [SECRETS]: { secrets: TWO_SECRETS },
      [MODELS_PATH]: MODELS,
      [`GET /api/v1/models/${INSTALLER_NAME}/file`]: apiError(500, 'internal', "The model's file can't be read."),
    })
    const { wrapper } = await mountApp('/detection')
    await clickIn(item(wrapper, "The installer's model"), 'Download')
    await clickInDialog('Download')
    expect(item(wrapper, "The installer's model").find('.v-alert').text()).toContain("The model's file can't be read.")
  })

  it("shows a use of the default on the default's card only, when another default's file is on the device", async () => {
    const builtIn: ModelOut = {
      ...MODELS.models[0],
      name: 'yolov6n.hef',
      kind: 'frigate_default',
      title: 'yolov6n.hef',
      files: [{ name: 'yolov6n.hef', size: 2048, sha256: null }],
    }
    signedIn(ADMIN, {
      [SECRETS]: { secrets: TWO_SECRETS },
      [MODELS_PATH]: { ...MODELS, detector: 'hailo8l', default: 'frigate_default', models: [builtIn, ...MODELS.models] },
      'POST /api/v1/models/default/use': json(202, { name: 'default', applied: 'frigate', restarts: ['frigate.service'] }),
    })
    const { wrapper } = await mountApp('/detection')
    await clickIn(item(wrapper, "Frigate's built-in model"), 'Use')
    await clickInDialog('Use')
    expect(item(wrapper, "Frigate's built-in model").text()).toContain('Frigate is restarting.')
    expect(item(wrapper, "The installer's model").text()).not.toContain('Frigate is restarting.')
  })

  it('asks with a primary button, since a download changes nothing', async () => {
    signedIn(ADMIN, { [SECRETS]: { secrets: TWO_SECRETS }, [MODELS_PATH]: WITH_BARE })
    const { wrapper } = await mountApp('/detection')
    await clickIn(item(wrapper, 'bare.tflite'), 'Download')
    const [confirm] = dialogButtons('Download')
    expect([...confirm.classList]).toContain('bg-primary')
    await clickInDialog('Cancel')
    await clickIn(item(wrapper, 'My model'), 'Delete')
    expect([...dialogButtons('Delete')[0].classList]).toContain('bg-error')
  })

  it('deletes after the confirm and reloads the list', async () => {
    const gone = { ...MODELS, models: MODELS.models.filter((model) => model.name !== 'mine.tflite') }
    const api = signedIn(ADMIN, {
      [SECRETS]: { secrets: TWO_SECRETS },
      [MODELS_PATH]: changesAfter(1, MODELS, gone),
      'DELETE /api/v1/models/mine.tflite': json(204, null),
    })
    const { wrapper } = await mountApp('/detection')
    // Only a model that isn't running and isn't the installer's can be deleted
    expect(wrapper.findAll('main button').filter((b) => b.text().trim() === 'Delete')).toHaveLength(1)
    await clickIn(item(wrapper, 'My model'), 'Delete')
    expect(dialogText()).toContain('Delete My model?')
    expect(dialogText()).toContain("Both of its files are removed from the device. This can't be undone.")
    await clickInDialog('Delete')
    expect(api.sent.some((r) => r.method === 'DELETE' && r.path === '/api/v1/models/mine.tflite')).toBe(true)
    expect(modelCalls(api)).toBe(2)
    expect(wrapper.findAll('.model').some((i) => i.text().includes('My model'))).toBe(false)
    // The count goes down, and the result stands above the cards
    const others = section(wrapper, 'Other models on this device (1)')
    expect(others.text()).toContain('Deleted My model.')
    expect(others.text().indexOf('Deleted My model.')).toBeLessThan(others.text().indexOf("The installer's model"))
  })

  it("lists Frigate's own Hailo model as its built-in model, running and with only Download", async () => {
    const builtIn: ModelOut = {
      ...MODELS.models[0],
      name: 'yolov6n.hef',
      kind: 'frigate_default',
      title: 'yolov6n.hef',
      files: [
        { name: 'yolov6n.hef', size: 2048, sha256: 'e5a00aa9991ac8a5ee3109844d84a55583bd20572ad3ffcd42792f3c36b183ad' },
      ],
      running: true,
    }
    signedIn(ADMIN, {
      [SECRETS]: { secrets: TWO_SECRETS },
      [MODELS_PATH]: {
        ...MODELS,
        detector: 'hailo8l',
        default: 'frigate_default',
        running: { name: null, kind: 'frigate_default', source: 'frigate' },
        models: [builtIn, MINE],
      },
    })
    const { wrapper } = await mountApp('/detection')
    expect(fact(wrapper, 'Running model')).toBe("Frigate's built-in model")
    const entry = wrapper.find('.model.in-use')
    expect(entry.text()).toContain("Frigate's built-in model")
    expect(cardActions(entry)).toEqual(['Download'])
    expect(entry.text()).toContain('In use')
    expect(entry.text()).not.toContain('incomplete')
    // Like the installer's entry, it has no sidecar: its file name is its facts line, shown once
    expect(entry.text().split('yolov6n.hef')).toHaveLength(2)
    expect(entry.text()).toContain('2.0 KB, SHA-256 e5a00aa9991a')
    expect(wrapper.findAll('main button').filter((b) => b.text().trim() === 'Delete')).toHaveLength(1)
  })

  it('disables Use for a model built for another detector, with the reason', async () => {
    const models = [MODELS.models[0], MODELS.models[1], { ...MINE, detectors: ['hailo8l'], usable: false }]
    signedIn(ADMIN, { [SECRETS]: { secrets: TWO_SECRETS }, [MODELS_PATH]: { ...MODELS, models } })
    const { wrapper } = await mountApp('/detection')
    const mine = item(wrapper, 'My model')
    const use = mine.findAll('button').find((b) => b.text().trim() === 'Use')!
    expect(use.attributes('disabled')).toBeDefined()
    expect(mine.text()).toContain("It's built for hailo8l, and this device detects with edgetpu.")
  })

  it("uses the installer's model from its own block", async () => {
    vi.useFakeTimers()
    const api = signedIn(ADMIN, {
      [SECRETS]: { secrets: TWO_SECRETS },
      [MODELS_PATH]: changesAfter(2, MODELS, running(MODELS.models[0].name, 'installer_default')),
      'POST /api/v1/models/default/use': json(202, { name: 'default', applied: 'frigate', restarts: ['frigate.service'] }),
    })
    const { wrapper } = await mountApp('/detection')
    await clickIn(item(wrapper, "The installer's model"), 'Use')
    expect(dialogText()).toContain("Use the installer's model?")
    await clickInDialog('Use')
    expect(api.sent.filter((r) => r.method === 'POST').map((r) => r.path)).toEqual(['/api/v1/models/default/use'])
    await vi.advanceTimersByTimeAsync(3000)
    expect(wrapper.text()).toContain('Frigate is restarting.')
    await vi.advanceTimersByTimeAsync(3000)
    expect(wrapper.text()).toContain("Frigate runs the installer's model.")
    const installer = wrapper.find('.model.in-use')
    expect(installer.text()).toContain("The installer's model")
    expect(installer.text()).toContain("Frigate runs the installer's model.") // the result moved with its block
    expect(cardActions(installer)).toEqual(['Download'])
    const plus = item(wrapper, 'Test site yolov9')
    expect(section(wrapper, 'Other models').element.contains(plus.element)).toBe(true)
    expect(cardActions(plus)).toEqual(['Use', 'Download'])
  })

  const NOTHING_RUNS = MODELS.models.map((model) => ({ ...model, running: false }))
  it.each([
    ["Frigate's built-in model", true, { ...MODELS, default: 'frigate_default' }, 3],
    [
      "Frigate's built-in model",
      false,
      {
        ...MODELS,
        default: 'frigate_default',
        running: { name: null, kind: 'frigate_default', source: 'frigate' },
        models: NOTHING_RUNS,
      },
      3,
    ],
    ["The installer's model", false, running(MODELS.models[0].name, 'installer_default'), 2],
    ["The installer's model", false, { ...MODELS, default: null }, 2],
  ] as [string, boolean, ModelsState, number][])(
    'the block %s offers Use: %s (row %#)',
    async (title, offersUse, state, others) => {
      signedIn(ADMIN, { [SECRETS]: { secrets: TWO_SECRETS }, [MODELS_PATH]: state })
      const { wrapper } = await mountApp('/detection')
      const block = item(wrapper, title)
      expect(cardActions(block).includes('Use')).toBe(offersUse)
      expect(headings(wrapper)).toContain(`Other models on this device (${others})`)
      // The default Frigate runs is the block in use; one that doesn't run is with the others
      expect(block.classes('in-use')).toBe(state.running.kind === state.default)
      if (state.default === null) {
        expect(wrapper.findAll('.model').some((m) => m.text().includes("Frigate's built-in model"))).toBe(false)
      }
    },
  )

  it('shows the results of models named "default" and "list" under those models', async () => {
    const named = (name: string): ModelOut => ({ ...MINE, name, title: `Model ${name}`, files: [] })
    const refused = (name: string) => apiError(409, 'conflict', `Refused ${name}.`)
    signedIn(ADMIN, {
      [SECRETS]: { secrets: TWO_SECRETS },
      [MODELS_PATH]: { ...MODELS, models: [...MODELS.models, named('default'), named('list')] },
      'POST /api/v1/models/default/use': json(500, null), // the device's default; the page must not call it
      'DELETE /api/v1/models/default': refused('default'),
      'DELETE /api/v1/models/list': refused('list'),
    })
    const { wrapper } = await mountApp('/detection')
    for (const name of ['default', 'list']) {
      await clickIn(item(wrapper, `Model ${name}`), 'Delete')
      await clickInDialog('Delete')
      expect(item(wrapper, `Model ${name}`).find('.v-alert').text()).toContain(`Refused ${name}.`)
      expect(wrapper.findAll('main .v-alert').map((a) => a.text())).toEqual([`Refused ${name}.`])
    }
  })

  it('shows Upload with nothing to open, under the other models heading', async () => {
    signedIn(ADMIN, { [SECRETS]: { secrets: TWO_SECRETS }, [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    const upload = section(wrapper, 'Other models').findAll('button').find((b) => b.text().trim() === 'Upload a model')!
    expect(upload.element.closest('.v-expansion-panel')).toBeNull()
    await click(wrapper, 'Upload a model')
    expect(dialogText()).toContain('A zip or tar.gz of the model file and its .json, not of a folder.')
  })

  it('shows Upload when there are no other models', async () => {
    const alone: ModelsState = { ...MODELS, default: null, models: [MODELS.models[1]] }
    signedIn(ADMIN, { [SECRETS]: { secrets: TWO_SECRETS }, [MODELS_PATH]: alone })
    const { wrapper } = await mountApp('/detection')
    expect(section(wrapper, 'Other models').findAll('button').map((b) => b.text().trim())).toEqual(['Upload a model'])
  })
})

describe('LabelChips', () => {
  afterEach(() => {
    Reflect.deleteProperty(navigator, 'clipboard')
    Reflect.deleteProperty(window, 'isSecureContext')
  })

  const LABELS = ['person', 'bicycle', 'car']
  const chip = (wrapper: VueWrapper, label: string) => wrapper.findAll('.v-chip').find((c) => c.text() === label)!

  it('leaves chips plain and shows no legend without marks', () => {
    const wrapper = mountAlone(LabelChips, { labels: LABELS, markedLegend: 'Filled: tracked.', flaggedLegend: 'Amber.' })
    expect(chip(wrapper, 'car').classes()).toContain('v-chip--variant-outlined')
    expect(chip(wrapper, 'car').classes()).not.toContain('text-warning')
    expect(chip(wrapper, 'car').classes()).not.toContain('text-primary')
    expect(wrapper.text()).not.toContain('Filled: tracked.')
    expect(wrapper.text()).not.toContain('Amber.')
  })

  it('fills a marked chip, and shows its legend only when a chip has the mark', () => {
    const wrapper = mountAlone(LabelChips, { labels: LABELS, marked: ['person', 'dog'], markedLegend: 'Filled: tracked.' })
    expect(chip(wrapper, 'person').classes()).toEqual(expect.arrayContaining(['v-chip--variant-tonal', 'text-primary']))
    expect(chip(wrapper, 'car').classes()).toContain('v-chip--variant-outlined')
    expect(wrapper.text()).toContain('Filled: tracked.')
    const none = mountAlone(LabelChips, { labels: LABELS, marked: ['dog'], markedLegend: 'Filled: tracked.' })
    expect(none.text()).not.toContain('Filled: tracked.')
  })

  it('outlines a flagged chip in amber, over a mark, with its legend', () => {
    const wrapper = mountAlone(LabelChips, {
      labels: LABELS,
      marked: ['person'],
      flagged: ['person', 'car'],
      flaggedLegend: 'Amber: not recognised.',
    })
    for (const label of ['person', 'car']) {
      expect(chip(wrapper, label).classes()).toEqual(expect.arrayContaining(['v-chip--variant-outlined', 'text-warning']))
    }
    expect(chip(wrapper, 'person').classes()).not.toContain('text-primary')
    expect(wrapper.text()).toContain('Amber: not recognised.')
    const none = mountAlone(LabelChips, { labels: LABELS, flagged: ['dog'], flaggedLegend: 'Amber: not recognised.' })
    expect(none.text()).not.toContain('Amber: not recognised.')
  })

  it('titles the list with an h4', () => {
    const wrapper = mountAlone(LabelChips, { title: 'Objects it recognises (3)', labels: LABELS })
    expect(wrapper.find('h4').text()).toBe('Objects it recognises (3)')
    expect(wrapper.find('h3').exists()).toBe(false)
  })

  it('still copies every label, whatever its mark', async () => {
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
    const wrapper = mountAlone(LabelChips, { labels: LABELS, marked: ['person'], flagged: ['car'] })
    await wrapper.find('button').trigger('click')
    expect(writeText).toHaveBeenCalledWith('person, bicycle, car')
  })
})

describe('ModelBlock', () => {
  const [INSTALLER, , MINE] = MODELS.models
  const listed = (model: ModelOut): Block => ({
    key: model.name,
    title: model.title,
    facts: 'the facts',
    model,
    kind: model.kind,
    inUse: model.running,
  })
  const card = (block: Block, props: Record<string, unknown> = {}) =>
    mountAlone(ModelBlock, {
      block,
      admin: true,
      busy: null,
      working: false,
      result: null,
      useBlocked: null,
      canUse: true,
      tracked: ['person', 'dog'],
      missing: [],
      lists: null,
      ...props,
    })
  const title = (wrapper: VueWrapper) => wrapper.find('.v-expansion-panel-title')
  const fold = (wrapper: VueWrapper) => wrapper.find('.v-expansion-panel-text')
  const button = (wrapper: VueWrapper, text: string) => wrapper.findAll('button').find((b) => b.text().trim() === text)!

  it('titles the card with an h3 and keeps the facts and the buttons outside the fold', () => {
    const wrapper = card(listed(MINE))
    expect(wrapper.find('h3').text()).toBe('My model')
    expect(wrapper.find('h3').classes()).toEqual(expect.arrayContaining(['text-body-1', 'text-break']))
    expect(fold(wrapper).text()).not.toContain('the facts')
    for (const text of ['Use', 'Download', 'Delete']) {
      expect(button(wrapper, text).element.closest('.v-expansion-panel')).toBeNull()
    }
  })

  it('keeps a closed fold titled "Files and objects" for a model with labels, with its files and objects inside', async () => {
    const wrapper = card(listed(MINE))
    expect(title(wrapper).text()).toBe('Files and objects')
    expect(title(wrapper).attributes('aria-expanded')).toBe('false')
    expect(title(wrapper).element.closest('h1, h2, h3, h4')).toBeNull() // a plain button, not a heading
    expect(fold(wrapper).text()).toContain('mine.tflite, 2.0 KB, SHA-256 e5a00aa9991a')
    expect(fold(wrapper).text()).toContain('mine.tflite.json, 417 bytes')
    expect(fold(wrapper).find('h4').text()).toBe('Objects it recognises (3)')
    expect(fold(wrapper).text()).toContain('Filled: tracked on this device.')
    const person = fold(wrapper).findAll('.v-chip').find((c) => c.text() === 'person')!
    expect(person.classes()).toContain('v-chip--variant-tonal')
    await title(wrapper).trigger('click')
    expect(title(wrapper).attributes('aria-expanded')).toBe('true')
  })

  it('titles the fold "Files" for a model without labels', () => {
    const wrapper = card(listed(INSTALLER))
    expect(title(wrapper).text()).toBe('Files')
    expect(fold(wrapper).text()).toContain('1.0 KB, SHA-256 5f70bf18a086')
    expect(fold(wrapper).find('h4').exists()).toBe(false)
  })

  it('has no fold on a block the page makes for a default with no file', () => {
    const made: Block = {
      key: '#frigate_default',
      title: "Frigate's built-in model",
      facts: 'Built into Frigate.',
      model: null,
      kind: 'frigate_default',
      inUse: false,
    }
    expect(card(made).find('.v-expansion-panel').exists()).toBe(false)
  })

  it('puts the running lists in the fold of the card in use, ahead of the files and instead of its own list', () => {
    const labels = { recognised: ['person', 'cat'], source: 'frigate' as const, tracked: ['person', 'dog'] }
    const plus = { ...MINE, running: true }
    const wrapper = card(listed(plus), { lists: { labels, listsDiffer: false, frigateAnswers: true }, missing: ['dog'] })
    expect(title(wrapper).text()).toBe('Files and objects')
    expect(fold(wrapper).findAll('h4').map((h) => h.text())).toEqual([
      'Objects the running model recognises (2)',
      'Objects tracked on this device (2, 1 not recognised)',
    ])
    expect(fold(wrapper).text()).not.toContain('Objects it recognises')
    expect(fold(wrapper).text()).not.toContain("Doesn't recognise")
    expect(fold(wrapper).text().indexOf('Objects tracked on this device')).toBeLessThan(fold(wrapper).text().indexOf('mine.tflite, 2.0 KB'))
    expect(wrapper.find('.not-recognised .v-chip').text()).toBe('dog')
    expect(wrapper.find('.not-recognised').element.closest('.fold')).toBeNull()
  })

  it('titles the fold "Objects" for a block with lists and no files, and gives it no buttons without a model', () => {
    const labels = { recognised: null, source: null, tracked: [] }
    const made: Block = { key: '#running', title: 'Unknown model', facts: 'x', model: null, kind: null, inUse: true }
    const wrapper = card(made, { canUse: false, lists: { labels, listsDiffer: false, frigateAnswers: true } })
    expect(title(wrapper).text()).toBe('Objects')
    expect(wrapper.findAll('button').filter((b) => !b.classes('v-expansion-panel-title')).map((b) => b.text().trim())).toEqual([])
    expect(wrapper.text()).toContain('In use')
    expect(fold(wrapper).text()).not.toContain('SHA-256')
  })

  it('keeps the problem line outside the fold', () => {
    const wrapper = card(listed({ ...MINE, problem: 'The sidecar is missing.' }))
    expect(wrapper.text()).toContain('The sidecar is missing.')
    expect(fold(wrapper).text()).not.toContain('The sidecar is missing.')
  })

  it('names the tracked objects a switch would lose, as amber chips inside the fold', () => {
    const wrapper = card(listed(MINE), { missing: ['dog', 'cat'] })
    expect(fold(wrapper).text()).toContain("Doesn't recognise 2 objects tracked on this device:")
    const amber = fold(wrapper).findAll('.v-chip.text-warning').map((c) => c.text())
    expect(amber).toEqual(['dog', 'cat'])
    const one = card(listed(MINE), { missing: ['dog'] })
    expect(fold(one).text()).toContain("Doesn't recognise 1 object tracked on this device:")
    expect(fold(card(listed(MINE))).text()).not.toContain("Doesn't recognise")
  })

  it('offers Download for any model with a model file, and not for one with only a .json', () => {
    const texts = (wrapper: VueWrapper) => wrapper.findAll('button').map((b) => b.text().trim())
    expect(texts(card(listed(INSTALLER), { canUse: false }))).toContain('Download')
    const bare = { ...MINE, complete: false, files: [MINE.files[0]], labels: null }
    expect(texts(card(listed(bare)))).toContain('Download')
    const half = { ...MINE, complete: false, files: [MINE.files[1]], labels: null }
    expect(texts(card(listed(half)))).not.toContain('Download')
  })

  it('gives Use the most weight and marks Delete as destructive', () => {
    const wrapper = card(listed(MINE))
    expect(button(wrapper, 'Use').classes()).toEqual(expect.arrayContaining(['v-btn--variant-flat', 'bg-primary']))
    expect(button(wrapper, 'Download').classes()).toEqual(expect.arrayContaining(['v-btn--variant-outlined', 'text-primary']))
    expect(button(wrapper, 'Delete').classes()).toEqual(expect.arrayContaining(['v-btn--variant-outlined', 'text-error']))
  })
})
