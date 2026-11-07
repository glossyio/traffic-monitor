// The Detection page: the detector, the model Frigate runs, the models on the device, the two label lists, and for
// admins the Frigate+ key form.
import { flushPromises, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { components } from '../src/api/schema'
import { ADMIN, VIEWER, apiError, json, signedIn } from './fake-api'
import { click, clickInDialog, dialogText, mountApp } from './mount'

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

// The title (a button) of the panel whose title starts with `title`
function panel(wrapper: VueWrapper, title: string) {
  const found = wrapper.findAll('.v-expansion-panel-title').filter((t) => t.text().trim().startsWith(title))
  expect(found.length, `one panel titled "${title}…"`).toBe(1)
  return found[0]
}

// The panel (title and content) whose title starts with `title`
function panelOf(wrapper: VueWrapper, title: string) {
  const toggle = panel(wrapper, title)
  return wrapper.findAll('.v-expansion-panel').find((p) => p.element.contains(toggle.element))!
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

  it('shows the facts, the model in use, and the others behind a closed panel', async () => {
    signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    expect(headings(wrapper)).toEqual(['Object detection', 'What the model recognises', 'Frigate+ API key'])
    expect(wrapper.text()).toContain(
      'See which model Frigate detects objects with and what it recognises. Administrators can switch models and ' +
        'set the Frigate+ API key.',
    )
    expect(fact(wrapper, 'Detector')).toBe('edgetpu')
    expect(fact(wrapper, 'Running model')).toBe('Test site yolov9, a Frigate+ model')
    expect(wrapper.text()).not.toContain("Frigate isn't answering")

    const plus = wrapper.find('.model.in-use')
    expect(plus.text()).toContain('Test site yolov9')
    expect(plus.text()).toContain('In use')
    expect(plus.text()).toContain('0123456789abcdef0123456789abcdef') // the file name, which differs from the title
    expect(plus.text()).toContain('trained 2026-10-01, yolo-generic, for edgetpu, 320×320')
    expect(plus.text()).toContain('0123456789abcdef0123456789abcdef, 4.0 KB, SHA-256 ad7facb2586f')
    expect(plus.text()).toContain('0123456789abcdef0123456789abcdef.json, 433 bytes, SHA-256 0da6c00a63ab')
    const hash = plus.find('[title="ad7facb2586fc6e966c004d7d1d16b024f5805ff7cb47c7a85dabd8b48892ca7"]')
    expect(hash.text()).toBe('SHA-256 ad7facb2586f')
    expect(plus.element.closest('.v-expansion-panel')).toBeNull() // above the fold
    expect(wrapper.findAll('.model.in-use')).toHaveLength(1)

    const toggle = panel(wrapper, 'Other models on this device (2)')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(toggle.element.parentElement?.tagName).toBe('H3')
    await toggle.trigger('click')
    expect(toggle.attributes('aria-expanded')).toBe('true')
    const others = wrapper.findAll('.v-expansion-panel .model')
    expect(others.map((m) => m.find('.text-body-1').text())).toEqual(["The installer's model", 'My model'])
    expect(item(wrapper, 'My model').text()).not.toContain('In use')
    // The installer's block has no sidecar: its file name is its facts line, shown once
    const installer = item(wrapper, "The installer's model")
    expect(installer.text().split('yolov9-s-relu6-tpumax_512_int8_edgetpu.tflite')).toHaveLength(2)
    expect(installer.text()).not.toContain('trained')
    expect(installer.text()).toContain('1.0 KB, SHA-256 5f70bf18a086')
    expect(wrapper.text()).toContain('Frigate tracks only the objects that are in both lists.')
    for (const title of ['All objects the model recognises (3)', 'Objects tracked on this device (6)']) {
      expect(panel(wrapper, title).attributes('aria-expanded')).toBe('false')
      expect(panel(wrapper, title).element.parentElement?.tagName).toBe('H3')
    }
    expect(wrapper.findAll('h3').map((h) => h.text().trim())).toEqual([
      'Other models on this device (2)',
      'All objects the model recognises (3)',
      'Objects tracked on this device (6)',
    ])
  })

  it('opens each panel on its own, so both label lists and the models can be open at once', async () => {
    signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    const titles = ['Other models on this device', 'All objects the model recognises', 'Objects tracked on this device']
    for (const title of titles) await panel(wrapper, title).trigger('click')
    expect(titles.map((title) => panel(wrapper, title).attributes('aria-expanded'))).toEqual(['true', 'true', 'true'])
  })

  it("puts every model in the panel when Frigate's model is unknown", async () => {
    const unknown: ModelsState = {
      ...MODELS,
      running: { name: null, kind: null, source: null },
      models: MODELS.models.map((model) => ({ ...model, running: false })),
    }
    signedIn(VIEWER, { [MODELS_PATH]: unknown })
    const { wrapper } = await mountApp('/detection')
    expect(wrapper.find('.model.in-use').exists()).toBe(false)
    expect(fact(wrapper, 'Running model')).toBe('Unknown')
    expect(panel(wrapper, 'Other models on this device (3)').exists()).toBe(true)
  })

  it("makes a block for Frigate's built-in model when the device has no file for it", async () => {
    const cpu: ModelsState = {
      ...MODELS,
      detector: 'cpu',
      default: 'frigate_default',
      running: { name: null, kind: 'frigate_default', source: 'frigate' },
      models: [{ ...MODELS.models[2], running: false }],
    }
    signedIn(VIEWER, { [MODELS_PATH]: cpu })
    const { wrapper } = await mountApp('/detection')
    const builtIn = wrapper.find('.model.in-use')
    expect(builtIn.text()).toContain("Frigate's built-in model")
    expect(builtIn.text()).toContain('Built into Frigate.')
    expect(fact(wrapper, 'Running model')).toBe("Frigate's built-in model")
    expect(panel(wrapper, 'Other models on this device (1)').exists()).toBe(true)
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
    expect(headings(wrapper)).toContain('Frigate+ API key')
    const plus = wrapper.find('#frigate-plus').text()
    expect(plus).toContain(
      'When the device is online and has a Frigate+ API key, pick a Frigate+ model in Frigate, under Settings, System, ' +
        'Detectors and model, and Frigate downloads it.',
    )
    expect(plus).toContain(
      "When it's offline, an administrator can upload the model's two files on this page, as a package from whoever " +
        "trained the model or copied from another device's Frigate.",
    )
    expect(panel(wrapper, 'Frigate+ API key').text().trim()).toBe('Frigate+ API key') // no state for a viewer
    expect(wrapper.findAll('form')).toEqual([])
    // The label lists' Copy buttons are the only buttons: nothing that changes the device
    expect(actions(wrapper)).toEqual(['Copy', 'Copy'])
    expect(api.sent.some((r) => r.path === '/api/v1/secrets')).toBe(false) // viewers get 403 there
  })

  it('shows an admin the Frigate+ key form from GET /secrets', async () => {
    signedIn(ADMIN, { [MODELS_PATH]: MODELS, [SECRETS]: { secrets: TWO_SECRETS } })
    const { wrapper } = await mountApp('/detection')
    const toggle = panel(wrapper, 'Frigate+ API key')
    expect(toggle.text()).toContain('Not set')
    expect(toggle.element.parentElement?.tagName).toBe('H2')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    expect(wrapper.find('#frigate-plus form').exists()).toBe(true)
    expect(wrapper.find('#frigate-plus h3').exists()).toBe(false) // the title says it already
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
    expect(panel(plus.wrapper, 'Frigate+ API key').text()).toContain('Set, ending in ab12, in use')

    signedIn(ADMIN, { [MODELS_PATH]: running('mine.tflite', 'local'), [SECRETS]: { secrets: set } })
    const local = await mountApp('/detection')
    const title = panel(local.wrapper, 'Frigate+ API key').text()
    expect(title).toContain('Set, ending in ab12')
    expect(title).not.toContain('in use')
  })

  it('copies the recognised labels as comma-separated text', async () => {
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true })
    signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    await panel(wrapper, 'All objects the model recognises (3)').trigger('click')
    const recognises = panelOf(wrapper, 'All objects the model recognises (3)')
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
    expect(panel(wrapper, 'All objects the model recognises').text().trim()).toBe('All objects the model recognises')
    expect(panelOf(wrapper, 'All objects the model recognises').text()).toContain(
      "Frigate isn't answering, and the running model has no sidecar on the device.",
    )
    expect(panel(wrapper, 'Objects tracked on this device (2)').exists()).toBe(true)
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
  })

  it("says the running model's labels aren't known when Frigate answers without them", async () => {
    const unknown: ModelsState = { ...MODELS, labels: { recognised: null, source: null, tracked: ['person', 'car'] } }
    signedIn(VIEWER, { [MODELS_PATH]: unknown })
    const { wrapper } = await mountApp('/detection')
    expect(wrapper.text()).toContain("The running model's labels aren't known.")
    expect(panel(wrapper, 'All objects the model recognises').text().trim()).toBe('All objects the model recognises')
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
    expect(wrapper.find('.model.in-use').exists()).toBe(false)

    const unnamed = { ...MODELS, running: { name: null, kind: 'frigate_plus', source: 'frigate' } as const }
    signedIn(VIEWER, { [MODELS_PATH]: { ...unnamed, models: [MODELS.models[0]] } })
    const again = await mountApp('/detection')
    expect(fact(again.wrapper, 'Running model')).toBe('A Frigate+ model')
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

  it('is linked from the menu after Device', async () => {
    signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    const menu = wrapper.findAll('.v-navigation-drawer a').map((a) => a.attributes('href'))
    expect(menu.indexOf('/detection')).toBe(menu.indexOf('/device') + 1)
  })

  it("opens the key panel when a link names it, as the Status page's Set the key does", async () => {
    signedIn(ADMIN, { [MODELS_PATH]: MODELS, [SECRETS]: { secrets: TWO_SECRETS } })
    const scrolled = vi.fn()
    Element.prototype.scrollIntoView = scrolled
    const { wrapper } = await mountApp('/detection#frigate-plus')
    expect(panel(wrapper, 'Frigate+ API key').attributes('aria-expanded')).toBe('true')
    expect(scrolled).toHaveBeenCalled()
    const others = ['Other models on this device', 'All objects the model recognises', 'Objects tracked on this device']
    expect(others.map((title) => panel(wrapper, title).attributes('aria-expanded'))).toEqual(['false', 'false', 'false'])
  })

  it('opens the key panel for a viewer without asking for the secrets', async () => {
    const api = signedIn(VIEWER, { [MODELS_PATH]: MODELS })
    Element.prototype.scrollIntoView = vi.fn()
    const { wrapper } = await mountApp('/detection#frigate-plus')
    expect(panel(wrapper, 'Frigate+ API key').attributes('aria-expanded')).toBe('true')
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
    expect(item(wrapper, 'Test site yolov9').findAll('button').map((b) => b.text().trim())).not.toContain('Use')
    await panel(wrapper, 'Other models').trigger('click')
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
    expect(wrapper.find('.model.in-use').text()).toContain('My model') // moved above the fold, with its result
    expect(wrapper.find('.model.in-use').text()).toContain('Frigate runs My model.')
    expect(panel(wrapper, 'Other models on this device (2)').exists()).toBe(true)
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
    // The installer's model has no sidecar to package: its block has only Use
    expect(item(wrapper, "The installer's model").findAll('button').map((b) => b.text().trim())).toEqual(['Use'])
    await clickIn(item(wrapper, 'My model'), 'Download')
    expect(api.sent.at(-1)?.path).toBe('/api/v1/models/mine.tflite/package')
    expect(saved).toEqual(['mine.tflite.zip'])
    expect(blobs[0].size).toBe(zip.length)
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
    await panel(wrapper, 'Other models').trigger('click')
    await clickIn(item(wrapper, 'My model'), 'Delete')
    expect(dialogText()).toContain('Delete My model?')
    expect(dialogText()).toContain("Both of its files are removed from the device. This can't be undone.")
    await clickInDialog('Delete')
    expect(api.sent.some((r) => r.method === 'DELETE' && r.path === '/api/v1/models/mine.tflite')).toBe(true)
    expect(modelCalls(api)).toBe(2)
    expect(wrapper.findAll('.model').some((i) => i.text().includes('My model'))).toBe(false)
    // The panel stays open, its count goes down, and the result is inside it
    expect(panel(wrapper, 'Other models on this device (1)').attributes('aria-expanded')).toBe('true')
    expect(wrapper.find('.v-expansion-panel').text()).toContain('Deleted My model.')
  })

  it("lists Frigate's own Hailo model as its built-in model, running and with no buttons", async () => {
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
    expect(entry.findAll('button')).toHaveLength(0)
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
    expect(installer.findAll('button')).toHaveLength(0)
    const plus = item(wrapper, 'Test site yolov9')
    expect(plus.element.closest('.v-expansion-panel')).not.toBeNull()
    expect(plus.findAll('button').map((b) => b.text().trim())).toEqual(['Use', 'Download'])
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
      expect(block.findAll('button').map((b) => b.text().trim()).includes('Use')).toBe(offersUse)
      expect(panel(wrapper, `Other models on this device (${others})`).exists()).toBe(true)
      // The default Frigate runs is the block in use; one that doesn't run is in the panel
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

  it('opens the upload dialog from inside the other-models panel', async () => {
    signedIn(ADMIN, { [SECRETS]: { secrets: TWO_SECRETS }, [MODELS_PATH]: MODELS })
    const { wrapper } = await mountApp('/detection')
    const toggle = panel(wrapper, 'Other models')
    expect(toggle.text()).not.toContain('Upload a model')
    const upload = wrapper.findAll('button').find((b) => b.text().trim() === 'Upload a model')!
    expect(upload.element.closest('.v-expansion-panel-text')).not.toBeNull()
    await toggle.trigger('click')
    await click(wrapper, 'Upload a model')
    expect(dialogText()).toContain('A zip or tar.gz of the model file and its .json, not of a folder.')
  })
})
